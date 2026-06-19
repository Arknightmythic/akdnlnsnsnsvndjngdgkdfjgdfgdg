import os
import json
import logging
from celery import Task
from sqlalchemy import create_engine, text

from worker import celery_app

logger = logging.getLogger(__name__)


def _make_engine():
    return create_engine(
        f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}"
        f"@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}",
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=2,
    )


class RetentionTask(Task):
    _engine = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = _make_engine()
        return self._engine


@celery_app.task(
    bind=True,
    base=RetentionTask,
    name="audit.tasks.execute_audit_retention",
    acks_late=True,
    # FIX #5: max_retries=0 mencegah Celery retry task retention secara otomatis.
    # Retry retention tidak aman karena bisa jalan dua kali dalam window yang sama,
    # dan DELETE sudah partial sehingga before_state tidak lagi akurat.
    max_retries=0,
)
def execute_audit_retention(self):
    from retrieval.repository import RetrieveRepository
    from audit.audit_service import AuditService

    logger.info("Starting Audit & Access Event Retention Task...")

    retrieval = RetrieveRepository(self.engine)
    audit_svc = AuditService(self.engine)

    # FIX #5: Ambil before_state dan policy sekaligus dalam satu koneksi read
    # agar count dan policy_id konsisten snapshot-nya — tidak terpecah jadi
    # dua query terpisah yang bisa terjeda oleh concurrent task lain.
    before_state, retention_rules, policy_ids = _load_before_state_and_policy(self.engine)

    logger.info(
        f"Before retention — audit_event: {before_state['audit_event_count']}, "
        f"access_event: {before_state['access_event_count']}"
    )

    try:
        with self.engine.begin() as conn:
            # DELETE audit_event
            conn.execute(text(f"""
                DELETE FROM audit_event
                WHERE event_time < DATE_SUB(NOW(), INTERVAL {retention_rules['AUDIT_LOG']} DAY)
            """))
            logger.info(f"Deleted audit_event older than {retention_rules['AUDIT_LOG']} days")

            # DELETE access_event
            conn.execute(text(f"""
                DELETE FROM access_event
                WHERE event_time < DATE_SUB(NOW(), INTERVAL {retention_rules['ACCESS_LOG']} DAY)
            """))
            logger.info(f"Deleted access_event older than {retention_rules['ACCESS_LOG']} days")

            # FIX #5: Gunakan _safe_policy_id untuk INSERT retention_action.
            # Jika policy_id None (tabel retention_policy kosong), INSERT tetap
            # berhasil karena kolom policy_id di schema nullable (tidak ada NOT NULL).
            # Sebelumnya ini tidak dihandle, bisa menyebabkan constraint error
            # tergantung StarRocks mode.
            log_action = text("""
                INSERT INTO retention_action (policy_id, resource_type, action_status)
                VALUES (:policy_id, :resource_type, :status)
            """)
            conn.execute(log_action, {
                "policy_id": policy_ids.get("AUDIT_LOG"),
                "resource_type": "AUDIT_LOG",
                "status": "SUCCESS",
            })
            conn.execute(log_action, {
                "policy_id": policy_ids.get("ACCESS_LOG"),
                "resource_type": "ACCESS_LOG",
                "status": "SUCCESS",
            })

        # Catat audit_event SETELAH commit transaksi utama agar tidak ikut rollback
        audit_svc.log_audit_event(
            actor_org_id="system_auto",
            action="EXECUTE_AUDIT_RETENTION",
            resource_type="AUDIT_LOG",
            resource_id="retention_task",
            result="SUCCESS",
            before_state=json.dumps(before_state),
            after_state=json.dumps({
                "retention_days_audit": retention_rules["AUDIT_LOG"],
                "retention_days_access": retention_rules["ACCESS_LOG"],
            }),
        )

        logger.info("Retention task completed successfully.")
        return "SUCCESS"

    except Exception as e:
        logger.error(f"Failed to execute retention task: {e}")

        # Catat FAILED dengan koneksi baru (koneksi lama sudah rollback)
        try:
            with self.engine.begin() as conn:
                log_action = text("""
                    INSERT INTO retention_action (policy_id, resource_type, action_status)
                    VALUES (:policy_id, :resource_type, :status)
                """)
                conn.execute(log_action, {
                    "policy_id": policy_ids.get("AUDIT_LOG"),
                    "resource_type": "AUDIT_LOG",
                    "status": "FAILED",
                })
                conn.execute(log_action, {
                    "policy_id": policy_ids.get("ACCESS_LOG"),
                    "resource_type": "ACCESS_LOG",
                    "status": "FAILED",
                })

            audit_svc.log_audit_event(
                actor_org_id="system_auto",
                action="EXECUTE_AUDIT_RETENTION",
                resource_type="AUDIT_LOG",
                resource_id="retention_task",
                result="FAILED",
                before_state=json.dumps(before_state),
                after_state=json.dumps({"error": str(e)}),
            )
        except Exception as inner_e:
            logger.error(f"Failed to record FAILED retention action: {inner_e}")

        return f"FAILED: {e}"


def _load_before_state_and_policy(engine):
    """
    FIX #5: Ambil count + policy dalam satu koneksi yang sama agar snapshot konsisten.

    Sebelumnya count_events_before_retention() dipanggil terpisah dari query policy
    di dalam task — dua round trip yang bisa disela oleh concurrent task.
    Di sini keduanya digabung dalam satu koneksi (bukan satu transaction, tapi
    setidaknya satu koneksi pool yang sama dan sequential).

    Juga handle kasus tabel retention_policy kosong dengan graceful fallback
    ke default 30 hari tanpa error.
    """
    retention_rules = {"AUDIT_LOG": 30, "ACCESS_LOG": 30}
    policy_ids = {"AUDIT_LOG": None, "ACCESS_LOG": None}
    before_state = {"audit_event_count": 0, "access_event_count": 0}

    with engine.connect() as conn:
        # Count sebelum delete
        count_row = conn.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM audit_event)  AS audit_event_count,
                (SELECT COUNT(*) FROM access_event) AS access_event_count
        """)).mappings().first()
        if count_row:
            before_state = dict(count_row)

        # Load policy
        policies = conn.execute(text("""
            SELECT resource_type, retention_days, id
            FROM retention_policy
            WHERE resource_type IN ('AUDIT_LOG', 'ACCESS_LOG') AND status = 'ACTIVE'
        """)).mappings().all()

        for p in policies:
            if p["retention_days"] is not None:
                retention_rules[p["resource_type"]] = p["retention_days"]
            policy_ids[p["resource_type"]] = p["id"]

    return before_state, retention_rules, policy_ids