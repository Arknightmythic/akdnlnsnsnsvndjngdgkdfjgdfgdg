from celery import shared_task
from sqlalchemy import text
from ingestion.starrocks_connection import engine
import logging

logger = logging.getLogger(__name__)

@shared_task(name="audit.tasks.execute_audit_retention")
def execute_audit_retention():
    logger.info("Starting Audit & Access Event Retention Task...")

    try:
        with engine.begin() as conn:
            # 1. Ambil policy untuk AUDIT dan ACCESS log (default 30 hari jika belum ada di tabel)
            # Untuk PoC, kita asumsikan ID policy-nya, atau gunakan logic fallback
            policy_query = text("""
                SELECT resource_type, retention_days, id 
                FROM retention_policy 
                WHERE resource_type IN ('AUDIT_LOG', 'ACCESS_LOG') AND status = 'ACTIVE'
            """)
            policies = conn.execute(policy_query).mappings().all()

            # Jika tabel retention_policy masih kosong, kita pakai hardcode 30 hari untuk PoC
            retention_rules = {
                "AUDIT_LOG": 30,
                "ACCESS_LOG": 30
            }
            policy_ids = {}

            for p in policies:
                retention_rules[p["resource_type"]] = p["retention_days"]
                policy_ids[p["resource_type"]] = p["id"]

            # 2. Eksekusi DELETE untuk audit_event
            audit_del_query = text(f"""
                DELETE FROM audit_event 
                WHERE event_time < DATE_SUB(NOW(), INTERVAL {retention_rules['AUDIT_LOG']} DAY)
            """)
            conn.execute(audit_del_query)
            
            # 3. Eksekusi DELETE untuk access_event
            access_del_query = text(f"""
                DELETE FROM access_event 
                WHERE event_time < DATE_SUB(NOW(), INTERVAL {retention_rules['ACCESS_LOG']} DAY)
            """)
            conn.execute(access_del_query)

            # 4. Catat history eksekusi retention (Opsional untuk PoC, tapi bagus untuk tracking)
            log_action = text("""
                INSERT INTO retention_action (policy_id, resource_type, action_status)
                VALUES (:policy_id, :resource_type, :status)
            """)
            
            conn.execute(log_action, {
                "policy_id": policy_ids.get("AUDIT_LOG", 0), 
                "resource_type": "AUDIT_LOG", 
                "status": "SUCCESS"
            })

            logger.info("Retention task completed successfully.")
            return "SUCCESS"

    except Exception as e:
        logger.error(f"Failed to execute retention task: {e}")
        return f"FAILED: {e}"