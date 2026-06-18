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
)
def execute_audit_retention(self):
    logger.info("Starting Audit & Access Event Retention Task...")

    # BEFORE_STATE: hitung jumlah baris SEBELUM DELETE.
    # Dilakukan di luar transaksi utama agar count tidak terpengaruh
    # jika transaksi kemudian di-rollback karena error.
    from retrieval.repository import RetrieveRepository
    from audit.audit_service import AuditService

    retrieval    = RetrieveRepository(self.engine)
    before_state = retrieval.count_events_before_retention()
    logger.info(
        f"Before retention — audit_event: {before_state['audit_event_count']}, "
        f"access_event: {before_state['access_event_count']}"
    )

    try:
        with self.engine.begin() as conn:
            # 1. Ambil policy AUDIT dan ACCESS log
            policy_query = text("""
                SELECT resource_type, retention_days, id
                FROM retention_policy
                WHERE resource_type IN ('AUDIT_LOG', 'ACCESS_LOG') AND status = 'ACTIVE'
            """)
            policies = conn.execute(policy_query).mappings().all()

            retention_rules = {"AUDIT_LOG": 30, "ACCESS_LOG": 30}
            policy_ids      = {"AUDIT_LOG": None, "ACCESS_LOG": None}

            for p in policies:
                retention_rules[p["resource_type"]] = p["retention_days"]
                policy_ids[p["resource_type"]]      = p["id"]

            # 2. DELETE audit_event
            conn.execute(text(f"""
                DELETE FROM audit_event
                WHERE event_time < DATE_SUB(NOW(), INTERVAL {retention_rules['AUDIT_LOG']} DAY)
            """))
            logger.info(f"Deleted audit_event older than {retention_rules['AUDIT_LOG']} days")

            # 3. DELETE access_event
            conn.execute(text(f"""
                DELETE FROM access_event
                WHERE event_time < DATE_SUB(NOW(), INTERVAL {retention_rules['ACCESS_LOG']} DAY)
            """))
            logger.info(f"Deleted access_event older than {retention_rules['ACCESS_LOG']} days")

            # 4. Catat ke retention_action untuk kedua resource type
            log_action = text("""
                INSERT INTO retention_action (policy_id, resource_type, action_status)
                VALUES (:policy_id, :resource_type, :status)
            """)
            conn.execute(log_action, {
                "policy_id": policy_ids["AUDIT_LOG"],
                "resource_type": "AUDIT_LOG",
                "status": "SUCCESS",
            })
            conn.execute(log_action, {
                "policy_id": policy_ids["ACCESS_LOG"],
                "resource_type": "ACCESS_LOG",
                "status": "SUCCESS",
            })

        # 5. Catat audit_event untuk operasi retention itu sendiri,
        #    dengan before_state = jumlah baris sebelum dihapus.
        #    Dibuat SETELAH transaksi commit agar tidak ikut di-rollback.
        AuditService(self.engine).log_audit_event(
            actor_org_id="system_auto",
            action="EXECUTE_AUDIT_RETENTION",
            resource_type="AUDIT_LOG",
            resource_id="retention_task",
            result="SUCCESS",
            before_state=json.dumps(before_state),
            after_state=json.dumps({
                "retention_days_audit":  retention_rules["AUDIT_LOG"],
                "retention_days_access": retention_rules["ACCESS_LOG"],
            }),
        )

        logger.info("Retention task completed successfully.")
        return "SUCCESS"

    except Exception as e:
        logger.error(f"Failed to execute retention task: {e}")

        # Catat FAILED ke retention_action menggunakan koneksi baru
        try:
            with self.engine.begin() as conn:
                policy_query = text("""
                    SELECT resource_type, id
                    FROM retention_policy
                    WHERE resource_type IN ('AUDIT_LOG', 'ACCESS_LOG') AND status = 'ACTIVE'
                """)
                policies = conn.execute(policy_query).mappings().all()
                policy_ids_fallback = {"AUDIT_LOG": None, "ACCESS_LOG": None}
                for p in policies:
                    policy_ids_fallback[p["resource_type"]] = p["id"]

                log_action = text("""
                    INSERT INTO retention_action (policy_id, resource_type, action_status)
                    VALUES (:policy_id, :resource_type, :status)
                """)
                conn.execute(log_action, {
                    "policy_id": policy_ids_fallback["AUDIT_LOG"],
                    "resource_type": "AUDIT_LOG",
                    "status": "FAILED",
                })
                conn.execute(log_action, {
                    "policy_id": policy_ids_fallback["ACCESS_LOG"],
                    "resource_type": "ACCESS_LOG",
                    "status": "FAILED",
                })

            # Catat juga ke audit_event dengan before_state
            AuditService(self.engine).log_audit_event(
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