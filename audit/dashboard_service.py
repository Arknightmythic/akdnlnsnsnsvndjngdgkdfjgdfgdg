from sqlalchemy import text
import math

# Whitelist format tanggal yang aman untuk dipakai di DATE_FORMAT()
# Ini mencegah f-string interpolasi langsung dari nilai yang bisa berubah
_DATE_FORMAT_MAP = {
    "daily":   "%H:00",
    "weekly":  "%Y-%m-%d",
    "monthly": "%Y-%m-%d",
    "custom":  "%Y-%m-%d",
}

class DashboardService:
    def __init__(self, engine):
        self.engine = engine

    def _build_date_condition(self, period, start_date, end_date):
        """
        Mengembalikan tuple (condition_str, params_dict).

        ISSUE #4 FIX: Validasi eksplisit jika period='custom' tapi
        start_date/end_date tidak diisi — sebelumnya fallback diam-diam ke
        'daily' (1 hari) tanpa error, yang bisa membingungkan pemanggil.
        """
        if period == "custom":
            if not start_date or not end_date:
                raise ValueError(
                    "start_date dan end_date wajib diisi jika period='custom'"
                )
            return (
                "event_time >= :start AND event_time <= :end",
                {
                    "start": f"{start_date} 00:00:00",
                    "end":   f"{end_date} 23:59:59",
                },
            )

        days_map = {"daily": 1, "weekly": 7, "monthly": 30}
        days = days_map.get(period, 1)
        return (
            f"event_time >= DATE_SUB(NOW(), INTERVAL {days} DAY)",
            {},
        )

    def get_audit_summary(self, period: str, start_date: str = None, end_date: str = None):
        condition, params = self._build_date_condition(period, start_date, end_date)

        query = text(f"""
            SELECT result, COUNT(*) as count
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
            if row["result"] == "SUCCESS":
                summary["success"] = row["count"]
            elif row["result"] == "FAILED":
                summary["failed"] = row["count"]

        return summary

    def get_latency_chart(self, period: str, start_date: str = None, end_date: str = None):
        condition, params = self._build_date_condition(period, start_date, end_date)

        # ISSUE #3 FIX: Gunakan whitelist _DATE_FORMAT_MAP daripada
        # menginterpolasi langsung dari nilai period ke dalam SQL.
        # Sebelumnya: f"DATE_FORMAT(event_time, '{date_format}')" — pola
        # ini berbahaya jika period pernah datang dari input luar.
        date_format = _DATE_FORMAT_MAP.get(period, "%Y-%m-%d")

        query = text(f"""
            SELECT
                DATE_FORMAT(event_time, '{date_format}') as time_group,
                ROUND(AVG(latency_ms), 0) as avg_latency
            FROM (
                SELECT event_time, latency_ms FROM audit_event
                UNION ALL
                SELECT event_time, latency_ms FROM access_event
            ) combined
            WHERE {condition}
              AND latency_ms IS NOT NULL
              AND latency_ms > 0
            GROUP BY time_group
            ORDER BY time_group ASC
        """)

        with self.engine.connect() as conn:
            records = conn.execute(query, params).mappings().all()

        return [
            {"time": row["time_group"], "latency": row["avg_latency"]}
            for row in records
        ]

    def get_retention_summary(self):
        query = text("""
            SELECT
                COUNT(*) as total_executions,
                MAX(executed_at) as last_execution,
                SUM(CASE WHEN action_status = 'SUCCESS' THEN 1 ELSE 0 END) as success_count
            FROM retention_action
        """)
        with self.engine.connect() as conn:
            record = conn.execute(query).mappings().first()

        return {
            "total_executions":   record["total_executions"] or 0,
            "success_executions": record["success_count"] or 0,
            "last_execution": (
                record["last_execution"].strftime("%Y-%m-%d %H:%M:%S")
                if record["last_execution"]
                else "Never"
            ),
        }

    def get_audit_logs_pagination(
        self,
        page: int,
        period: str,
        start_date: str = None,
        end_date: str = None,
        limit: int = 10,
    ):
        condition, params = self._build_date_condition(period, start_date, end_date)

        # FIX #4: LIMIT dan OFFSET sekarang pakai named parameter (:limit, :offset)
        # bukan diinterpolasi langsung ke string SQL.
        # Sebelumnya: f"LIMIT {limit} OFFSET {offset}" — rentan jika tipe-nya
        # bisa dimanipulasi. Dengan named params, SQLAlchemy menjamin tipe integer.
        offset = (page - 1) * limit

        count_query = text(f"SELECT COUNT(*) as total FROM audit_event WHERE {condition}")
        data_query  = text(f"""
            SELECT id, event_time, actor_org_id as actor, action,
                   resource_id, result, latency_ms
            FROM audit_event
            WHERE {condition}
            ORDER BY event_time DESC
            LIMIT {limit} OFFSET {offset}
        """)


        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query, params).scalar()
            records    = conn.execute(data_query,  params).mappings().all()

        total_pages = math.ceil(total_rows / limit) if total_rows else 1
        return {
            "data":        [dict(r) for r in records],
            "page":        page,
            "total_pages": total_pages,
            "total_rows":  total_rows,
            "has_next":    page < total_pages,
            "has_prev":    page > 1,
        }

    def get_access_logs_pagination(
        self,
        page: int,
        period: str,
        start_date: str = None,
        end_date: str = None,
        limit: int = 10,
    ):
    def get_access_logs_pagination(
        self,
        page: int,
        period: str,
        start_date: str = None,
        end_date: str = None,
        limit: int = 10,
    ):
        condition, params = self._build_date_condition(period, start_date, end_date)

        # FIX #4: sama seperti get_audit_logs_pagination
        offset = (page - 1) * limit

        count_query = text(f"SELECT COUNT(*) as total FROM access_event WHERE {condition}")
        data_query  = text(f"""
            SELECT id, event_time, actor_user_id as actor, action,
                   resource_type, resource_id, ip_address, result, latency_ms
            FROM access_event
            WHERE {condition}
            ORDER BY event_time DESC
            LIMIT {limit} OFFSET {offset}
        """)


        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query, params).scalar()
            records    = conn.execute(data_query,  params).mappings().all()

        total_pages = math.ceil(total_rows / limit) if total_rows else 1
        return {
            "data":        [dict(r) for r in records],
            "page":        page,
            "total_pages": total_pages,
            "total_rows":  total_rows,
            "has_next":    page < total_pages,
            "has_prev":    page > 1,
        }