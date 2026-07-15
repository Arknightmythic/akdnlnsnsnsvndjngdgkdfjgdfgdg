from sqlalchemy import text
import math

# Whitelist period yang valid — tolak apapun di luar ini
_ALLOWED_PERIODS = {"daily", "weekly", "monthly", "custom"}

# Whitelist format tanggal untuk DATE_FORMAT() — tidak pernah diinterpolasi dari input user
_DATE_FORMAT_MAP = {
    "daily":   "%H:00",
    "weekly":  "%Y-%m-%d",
    "monthly": "%Y-%m-%d",
    "custom":  "%Y-%m-%d",
}

# Mapping period ke jumlah hari — hardcoded, tidak dari user
_DAYS_MAP = {"daily": 1, "weekly": 7, "monthly": 30}


class DashboardService:
    def __init__(self, engine):
        self.engine = engine

    def _validate_period(self, period: str) -> str:
        # FIX #3/#4: Validasi eksplisit sebelum apapun dipakai.
        # Sebelumnya tidak ada pengecekan ini, jadi kalau period somehow
        # lolos dari Pydantic dengan nilai aneh, bisa masuk ke SQL string.
        if period not in _ALLOWED_PERIODS:
            raise ValueError(
                f"Parameter 'period' tidak valid: '{period}'. "
                f"Nilai yang diizinkan: {sorted(_ALLOWED_PERIODS)}"
            )
        return period

    def _build_date_condition(self, period: str, start_date: str, end_date: str):
        """
        Mengembalikan tuple (condition_str, params_dict).

        FIX #3: condition_str untuk branch daily/weekly/monthly sekarang
        menggunakan :interval_days sebagai named parameter, bukan f-string integer.
        Meskipun nilai days dari dict hardcoded (bukan user input), ini lebih
        defensively correct dan konsisten dengan branch custom yang sudah pakai params.

        FIX #4: Validasi eksplisit untuk period='custom' tetap dipertahankan.
        """
        period = self._validate_period(period)

        if period == "custom":
            if not start_date or not end_date:
                raise ValueError(
                    "start_date dan end_date wajib diisi jika period='custom'"
                )
            return (
                "event_time >= :start AND event_time <= :end",
                {
                    "start": f"{start_date} 00:00:00",
                    "end": f"{end_date} 23:59:59",
                },
            )

        days = _DAYS_MAP[period]  # Selalu ada karena sudah divalidasi di atas
        return (
            "event_time >= DATE_SUB(NOW(), INTERVAL :interval_days DAY)",
            {"interval_days": days},
        )

    def get_audit_summary(self, period: str, start_date: str = None, end_date: str = None):
        condition, params = self._build_date_condition(period, start_date, end_date)

        # FIX #3: date_format dari whitelist, condition pakai named params — aman
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
            if row["result"] == "SUCCESS":
                summary["success"] = row["count"]
            elif row["result"] == "FAILED":
                summary["failed"] = row["count"]

            if row["result"] == "SUCCESS":
                summary["success"] = row["count"]
            elif row["result"] == "FAILED":
                summary["failed"] = row["count"]

        return summary

    def get_latency_chart(self, period: str, start_date: str = None, end_date: str = None):
        condition, params = self._build_date_condition(period, start_date, end_date)

        # FIX #3: date_format diambil dari whitelist dict, TIDAK dari input user
        date_format = _DATE_FORMAT_MAP[period]  # Selalu ada karena sudah divalidasi

        query = text(f"""
            SELECT
                DATE_FORMAT(event_time, '{date_format}') as time_group,
                ROUND(AVG(latency_ms), 0) as avg_latency
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
            SELECT
                COUNT(*) as total_executions,
                MAX(executed_at) as last_execution,
                SUM(CASE WHEN action_status = 'SUCCESS' THEN 1 ELSE 0 END) as success_count
            FROM retention_action
        """)
        with self.engine.connect() as conn:
            record = conn.execute(query).mappings().first()


        return {
            "total_executions": record["total_executions"] or 0,
            "success_executions": record["success_count"] or 0,
            "last_execution": (
                record["last_execution"].strftime("%Y-%m-%d %H:%M:%S")
                if record["last_execution"]
                else "Never"
            ),
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

        # FIX #4: LIMIT dan OFFSET sekarang pakai named parameter (:limit, :offset)
        # bukan diinterpolasi langsung ke string SQL.
        # Sebelumnya: f"LIMIT {limit} OFFSET {offset}" — rentan jika tipe-nya
        # bisa dimanipulasi. Dengan named params, SQLAlchemy menjamin tipe integer.
        offset = (page - 1) * limit
        params = {**params, "limit": limit, "offset": offset}

        count_query = text(f"""
            SELECT COUNT(*) as total FROM audit_event WHERE {condition}
        """)
        data_query = text(f"""
            SELECT id, event_time, actor_org_id as actor, action,
                   resource_id, result, latency_ms
            FROM audit_event
            WHERE {condition}
            ORDER BY event_time DESC
            LIMIT :limit OFFSET :offset
        """)

        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query, params).scalar()
            records = conn.execute(data_query, params).mappings().all()

        total_pages = math.ceil(total_rows / limit) if total_rows else 1
        return {
            "data": [dict(r) for r in records],
            "page": page,
            "total_pages": total_pages,
            "total_rows": total_rows,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }

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

        # FIX #4: sama seperti get_audit_logs_pagination
        offset = (page - 1) * limit
        params = {**params, "limit": limit, "offset": offset}

        count_query = text(f"""
            SELECT COUNT(*) as total FROM access_event WHERE {condition}
        """)
        data_query = text(f"""
            SELECT id, event_time, actor_user_id as actor, action,
                   resource_type, resource_id, ip_address, result, latency_ms
            FROM access_event
            WHERE {condition}
            ORDER BY event_time DESC
            LIMIT :limit OFFSET :offset
        """)

        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query, params).scalar()
            records = conn.execute(data_query, params).mappings().all()

        total_pages = math.ceil(total_rows / limit) if total_rows else 1
        return {
            "data": [dict(r) for r in records],
            "page": page,
            "total_pages": total_pages,
            "total_rows": total_rows,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }