from sqlalchemy import text
from datetime import datetime

class AuditService:
    def __init__(self, engine):
        self.engine = engine

    def log_audit_event(self, actor_org_id, action, resource_type, resource_id, result, before_state=None, after_state=None):
        query = text("""
            INSERT INTO audit_event (
                actor_user_id, actor_org_id, action, resource_type, 
                resource_id, before_state, after_state, result
            ) VALUES (
                :actor_user_id, :actor_org_id, :action, :resource_type, 
                :resource_id, :before_state, :after_state, :result
            )
        """)
        try:
            with self.engine.begin() as conn:
                conn.execute(query, {
                    "actor_user_id": "system_poc",
                    "actor_org_id": actor_org_id,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "before_state": before_state,
                    "after_state": after_state,
                    "result": result
                })
        except Exception as e:
            print(f"Failed to log audit event: {e}")

    def log_access_event(self, action, resource_type, resource_id, ip_address, result):
        query = text("""
            INSERT INTO access_event (
                actor_user_id, action, resource_type, resource_id, ip_address, result
            ) VALUES (
                :actor_user_id, :action, :resource_type, :resource_id, :ip_address, :result
            )
        """)
        try:
            with self.engine.begin() as conn:
                conn.execute(query, {
                    "actor_user_id": "anonymous_poc",
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "ip_address": ip_address,
                    "result": result
                })
        except Exception as e:
            print(f"Failed to log access event: {e}")