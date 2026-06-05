from sqlalchemy import text
import math

class DashboardService:
    def __init__(self, engine):
        self.engine = engine

    def _build_date_condition(self, period, start_date, end_date):
        # Mengembalikan string kondisi dan dictionary parameter untuk mencegah SQL Injection
        if period == "custom" and start_date and end_date:
            return "event_time >= :start AND event_time <= :end", {"start": f"{start_date} 00:00:00", "end": f"{end_date} 23:59:59"}
        
        days = 1
        if period == "weekly": days = 7
        elif period == "monthly": days = 30
        return f"event_time >= DATE_SUB(NOW(), INTERVAL {days} DAY)", {}

    def get_audit_summary(self, period: str, start_date: str = None, end_date: str = None):
        condition, params = self._build_date_condition(period, start_date, end_date)
        
        # Menggabungkan audit dan access event untuk perhitungan sukses/gagal
        query = text(f"""
            SELECT result, COUNT(*) as count 
            FROM (
                SELECT result, event_time FROM audit_event
                UNION ALL
                SELECT result, event_time FROM access_event
            ) combined
            WHERE {condition}
            GROUP BY result
        """)
        
        with self.engine.connect() as conn:
            records = conn.execute(query, params).mappings().all()
            
        summary = {"success": 0, "failed": 0}
        for row in records:
            if row["result"] == "SUCCESS": summary["success"] = row["count"]
            elif row["result"] == "FAILED": summary["failed"] = row["count"]
                
        return summary

    def get_latency_chart(self, period: str, start_date: str = None, end_date: str = None):
        condition, params = self._build_date_condition(period, start_date, end_date)
        date_format = '%Y-%m-%d' if period in ['weekly', 'monthly', 'custom'] else '%H:00'
        
        # Rata-rata latency gabungan
        query = text(f"""
            SELECT DATE_FORMAT(event_time, '{date_format}') as time_group, ROUND(AVG(latency_ms), 0) as avg_latency
            FROM (
                SELECT event_time, latency_ms FROM audit_event
                UNION ALL
                SELECT event_time, latency_ms FROM access_event
            ) combined
            WHERE {condition} AND latency_ms IS NOT NULL AND latency_ms > 0
            GROUP BY time_group ORDER BY time_group ASC
        """)
        
        with self.engine.connect() as conn:
            records = conn.execute(query, params).mappings().all()
            
        return [{"time": row["time_group"], "latency": row["avg_latency"]} for row in records]

    def get_retention_summary(self):
        query = text("""
            SELECT COUNT(*) as total_executions, MAX(executed_at) as last_execution,
                   SUM(CASE WHEN action_status = 'SUCCESS' THEN 1 ELSE 0 END) as success_count
            FROM retention_action
        """)
        with self.engine.connect() as conn:
            record = conn.execute(query).mappings().first()
            
        return {
            "total_executions": record["total_executions"] or 0,
            "success_executions": record["success_count"] or 0,
            "last_execution": record["last_execution"].strftime("%Y-%m-%d %H:%M:%S") if record["last_execution"] else "Never"
        }

    def get_audit_logs_pagination(self, page: int, period: str, start_date: str = None, end_date: str = None, limit: int = 10):
        condition, params = self._build_date_condition(period, start_date, end_date)
        offset = (page - 1) * limit
        
        count_query = text(f"SELECT COUNT(*) as total FROM audit_event WHERE {condition}")
        data_query = text(f"""
            SELECT id, event_time, actor_org_id as actor, action, resource_id, result, latency_ms 
            FROM audit_event 
            WHERE {condition} 
            ORDER BY event_time DESC LIMIT {limit} OFFSET {offset}
        """)
        
        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query, params).scalar()
            records = conn.execute(data_query, params).mappings().all()
            
        return {
            "data": [dict(r) for r in records], "page": page,
            "total_pages": math.ceil(total_rows / limit) if total_rows else 1,
            "total_rows": total_rows, "has_next": page < (math.ceil(total_rows / limit) if total_rows else 1), "has_prev": page > 1
        }

    def get_access_logs_pagination(self, page: int, period: str, start_date: str = None, end_date: str = None, limit: int = 10):
        condition, params = self._build_date_condition(period, start_date, end_date)
        offset = (page - 1) * limit
        
        count_query = text(f"SELECT COUNT(*) as total FROM access_event WHERE {condition}")
        data_query = text(f"""
            SELECT id, event_time, actor_user_id as actor, action, resource_type, resource_id, ip_address, result, latency_ms 
            FROM access_event 
            WHERE {condition} 
            ORDER BY event_time DESC LIMIT {limit} OFFSET {offset}
        """)
        
        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query, params).scalar()
            records = conn.execute(data_query, params).mappings().all()
            
        return {
            "data": [dict(r) for r in records], "page": page,
            "total_pages": math.ceil(total_rows / limit) if total_rows else 1,
            "total_rows": total_rows, "has_next": page < (math.ceil(total_rows / limit) if total_rows else 1), "has_prev": page > 1
        }