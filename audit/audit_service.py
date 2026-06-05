from sqlalchemy import text

class AuditService:
    def __init__(self, engine):
        self.engine = engine

    # [UPDATE] Tambahkan parameter latency_ms dengan default value 0
    def log_audit_event(self, actor_org_id, action, resource_type, resource_id, result, latency_ms=0, before_state=None, after_state=None):
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
            with self.engine.begin() as conn:
                conn.execute(query, {
                    "actor_user_id": "system_poc",
                    "actor_org_id": actor_org_id,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "before_state": before_state,
                    "after_state": after_state,
                    "result": result,
                    "latency_ms": latency_ms # <--- Binding variabel baru
                })
        except Exception as e:
            print(f"Failed to log audit event: {e}")

    # [UPDATE] Tambahkan parameter latency_ms untuk access event juga
    def log_access_event(self, action, resource_type, resource_id, ip_address, result, latency_ms=0):
        query = text("""
            INSERT INTO access_event (
                actor_user_id, action, resource_type, resource_id, ip_address, result, latency_ms
            ) VALUES (
                :actor_user_id, :action, :resource_type, :resource_id, :ip_address, :result, :latency_ms
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
                    "result": result,
                    "latency_ms": latency_ms # <--- Binding variabel baru
                })
        except Exception as e:
            print(f"Failed to log access event: {e}")