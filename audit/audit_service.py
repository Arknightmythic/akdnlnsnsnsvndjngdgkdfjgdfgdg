"""
audit/audit_service.py
----------------------
Backward-compatible wrapper di atas AuditWriter.

Semua caller yang sudah ada (ingestion, processing, reasoning, retrieval)
tidak perlu diubah — cukup import AuditService seperti biasa.

Untuk kode baru, disarankan langsung pakai AuditWriter agar lebih eksplisit.
"""

from audit.writer import AuditWriter


class AuditService:
    def __init__(self, engine):
        self._writer = AuditWriter(engine=engine, redis=None)

    def log_audit_event(
        self,
        actor_org_id,
        action,
        resource_type,
        resource_id,
        result,
        latency_ms=0,
        before_state=None,
        after_state=None,
        actor_user_id="system_poc",
    ):
        self._writer.log_audit(
            actor_org_id=actor_org_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            latency_ms=latency_ms,
            before_state=before_state,
            after_state=after_state,
            actor_user_id=actor_user_id,
        )

    def log_access_event(
        self,
        action,
        resource_type,
        resource_id,
        ip_address,
        result,
        latency_ms=0,
        actor_user_id="anonymous_poc",
    ):
        # Caller lama (ingestion/routes.py) pakai ini secara synchronous langsung ke DB.
        # Behavior dipertahankan — tulis langsung tanpa Redis.
        self._writer.log_access_sync(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            result=result,
            latency_ms=latency_ms,
            actor_user_id=actor_user_id,
        )