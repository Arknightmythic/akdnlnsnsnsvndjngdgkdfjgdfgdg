"""
audit/writer.py
---------------
Centralized audit writer untuk seluruh sistem Synchrono.

Sebelumnya ada inkonsistensi:
- ingestion & processing → tulis access_event LANGSUNG ke DB via AuditService
- retrieval & chatbot   → push ke Redis list dulu, di-flush tiap 10 detik

Ini berbahaya: kalau Redis restart, access log dari retrieval/chatbot hilang tanpa trace.

Solusi yang diterapkan di sini:
- audit_event  → SELALU tulis langsung ke DB (aksi sistem, harus reliable)
- access_event → SELALU via Redis queue + fallback langsung ke DB jika Redis gagal

Dengan ini semua caller cukup import AuditWriter dan pakai dua method yang sama.
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AuditWriter:
    """
    Satu-satunya pintu masuk untuk menulis audit trail di seluruh sistem.

    Cara pakai:
        writer = AuditWriter(engine=engine, redis=redis_client)
        writer.log_audit(actor_org_id="org_xyz", action="UPLOAD_FILE", ...)
        writer.log_access(action="VIEW_FILES", resource_type="LIST", ...)

    Parameter redis bersifat opsional. Jika None, access_event langsung ditulis ke DB
    (mode fallback, misalnya di dalam Celery worker yang tidak punya async redis).
    """

    def __init__(self, engine, redis=None):
        self._engine = engine
        self._redis = redis

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_audit(
        self,
        actor_org_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        result: str,
        latency_ms: int = 0,
        before_state: Optional[str] = None,
        after_state: Optional[str] = None,
        actor_user_id: str = "system_poc",
    ) -> None:
        """
        Tulis audit_event langsung ke StarRocks.
        Dipakai untuk: upload, matching, reasoning, retention, mark-completed.
        Selalu synchronous — harus reliable, tidak boleh hilang.
        """
        from sqlalchemy import text

        query = text("""
            INSERT INTO audit_event (
                actor_user_id, actor_org_id, action, resource_type,
                resource_id, before_state, after_state, result, latency_ms
            ) VALUES (
                :actor_user_id, :actor_org_id, :action, :resource_type,
                :resource_id, :before_state, :after_state, :result, :latency_ms
            )
        """)
        try:
            with self._engine.begin() as conn:
                conn.execute(query, {
                    "actor_user_id": actor_user_id,
                    "actor_org_id": actor_org_id,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "before_state": before_state,
                    "after_state": after_state,
                    "result": result,
                    "latency_ms": latency_ms,
                })
        except Exception as e:
            logger.error(f"[AuditWriter] Gagal tulis audit_event: {e}")

    async def log_access_async(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        ip_address: str,
        result: str = "SUCCESS",
        latency_ms: int = 0,
        actor_user_id: str = "anonymous_poc",
    ) -> None:
        """
        Catat access_event via Redis queue (async, non-blocking).
        Dipakai di FastAPI endpoint handler dengan BackgroundTasks.

        Jika Redis tidak tersedia, fallback langsung ke DB agar log tidak hilang.
        """
        payload = {
            "actor_user_id": actor_user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "ip_address": ip_address,
            "result": result,
            "latency_ms": latency_ms,
        }

        if self._redis is not None:
            try:
                await self._redis.rpush("audit_access_logs", json.dumps(payload))
                return
            except Exception as e:
                logger.warning(
                    f"[AuditWriter] Redis push gagal ({e}), fallback ke direct DB write"
                )

        # Fallback: tulis langsung ke DB jika Redis tidak tersedia
        self._write_access_to_db(payload)

    def log_access_sync(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        ip_address: str,
        result: str = "SUCCESS",
        latency_ms: int = 0,
        actor_user_id: str = "anonymous_poc",
    ) -> None:
        """
        Catat access_event langsung ke DB (synchronous).
        Dipakai di dalam Celery worker atau konteks non-async.
        """
        payload = {
            "actor_user_id": actor_user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "ip_address": ip_address,
            "result": result,
            "latency_ms": latency_ms,
        }
        self._write_access_to_db(payload)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write_access_to_db(self, payload: dict) -> None:
        from sqlalchemy import text

        query = text("""
            INSERT INTO access_event (
                actor_user_id, action, resource_type, resource_id,
                ip_address, result, latency_ms
            ) VALUES (
                :actor_user_id, :action, :resource_type, :resource_id,
                :ip_address, :result, :latency_ms
            )
        """)
        try:
            with self._engine.begin() as conn:
                conn.execute(query, payload)
        except Exception as e:
            logger.error(f"[AuditWriter] Gagal tulis access_event ke DB: {e}")