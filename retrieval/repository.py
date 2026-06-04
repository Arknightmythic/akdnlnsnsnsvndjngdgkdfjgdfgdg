from sqlalchemy import text, bindparam

class RetrieveRepository:
    def __init__(self, engine):
        self.engine = engine

    def get_graded_files(self, page, page_size):
        offset = (page - 1) * page_size

        count_query = text("""
            SELECT COUNT(*) AS total
            FROM uploaded_files
        """)

        data_query = text("""
            SELECT
                uf.file_id,
                uf.original_filename,
                uf.institution_name,
                uf.upload_timestamp,
                rg.grade_code as grade,
                uf.row_count,
                rp.process_name as processing_status,
                uf.is_sync
            FROM uploaded_files uf
            INNER JOIN ref_grades rg
                ON uf.grade = rg.grade_id
            INNER JOIN ref_process rp
                ON uf.processing_status = rp.process_id
            ORDER BY uf.upload_timestamp DESC
            LIMIT :limit
            OFFSET :offset
        """)

        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query).scalar()

            rows = conn.execute(
                data_query,
                {
                    "limit": page_size,
                    "offset": offset
                }
            ).mappings().all()

        return [dict(row) for row in rows], total_rows
    
    def get_synchronized_files(
        self,
        page,
        page_size,
        institution_name,
        grade,
        sync_status
    ):
        offset = (page - 1) * page_size

        where_clauses = [
            "uf.is_sync = true"
        ]

        params = {
            "limit": page_size,
            "offset": offset
        }

        if institution_name.strip():
            params["institution_name"] = f"%{institution_name}%"
            where_clauses.append("""
                LOWER(uf.institution_name) LIKE LOWER(:institution_name)
            """)

        if grade != "all":
            grade_codes = [g.strip() for g in grade.split(",") if g.strip()]
            if grade_codes:
                params["grade_codes"] = grade_codes
                where_clauses.append("rg.grade_code IN :grade_codes")

        if sync_status != "all":
            status_codes = [s.strip() for s in sync_status.split(",") if s.strip()]
            if status_codes:
                params["status_codes"] = status_codes
                where_clauses.append("rs.status_code IN :status_codes")

        where_sql = " AND ".join(where_clauses)

        count_query = text(f"""
            SELECT COUNT(*) AS total
            FROM uploaded_files uf
            JOIN ref_grades rg ON uf.grade = rg.grade_id
            JOIN ref_sync_statuses rs ON uf.sync_status = rs.sync_status_id
            WHERE {where_sql}
        """).bindparams(
            bindparam("grade_codes", expanding=True),
            bindparam("status_codes", expanding=True)
        )

        data_query = text(f"""
            SELECT
                uf.file_id,
                uf.original_filename,
                uf.institution_name,
                uf.upload_timestamp,
                uf.grade,
                uf.row_count,
                uf.is_sync,
                uf.sync_status
            FROM uploaded_files uf
            JOIN ref_grades rg ON uf.grade = rg.grade_id
            JOIN ref_sync_statuses rs ON uf.sync_status = rs.sync_status_id
            WHERE {where_sql}
            ORDER BY uf.upload_timestamp DESC
            LIMIT :limit
            OFFSET :offset
        """).bindparams(
            bindparam("grade_codes", expanding=True),
            bindparam("status_codes", expanding=True)
        )
        
        with self.engine.connect() as conn:

            total_rows = conn.execute(
                count_query,
                params
            ).scalar()

            rows = conn.execute(
                data_query,
                params
            ).mappings().all()

        return [dict(row) for row in rows], total_rows