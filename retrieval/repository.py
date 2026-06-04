from sqlalchemy import text

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

        where_conditions = []
        params = {
            "limit": page_size,
            "offset": offset
        }

        if institution_name and institution_name.strip("'").strip():
            where_conditions.append("LOWER(uf.institution_name) LIKE LOWER(:institution_name)")
            params["institution_name"] = f"%{institution_name.strip(chr(39)).strip()}%"

        if grade:
            grade_list = [g.strip() for g in str(grade).split(",") if g.strip()]
            if grade_list:
                placeholders = ", ".join([f":grade_{i}" for i in range(len(grade_list))])
                where_conditions.append(f"rg.grade_id IN ({placeholders})")
                for i, g in enumerate(grade_list):
                    params[f"grade_{i}"] = int(g)  

        if sync_status:
            status_list = [s.strip() for s in str(sync_status).split(",") if s.strip()]
            if status_list:
                placeholders = ", ".join([f":sync_status_{i}" for i in range(len(status_list))])
                where_conditions.append(f"rs.sync_status_id IN ({placeholders})")
                for i, s in enumerate(status_list):
                    params[f"sync_status_{i}"] = int(s)  

        where_clause = f"WHERE {' AND '.join(where_conditions)}" if where_conditions else ""

        count_query = text(f"""
            SELECT COUNT(*)
            FROM uploaded_files uf
            JOIN ref_grades rg ON uf.grade = rg.grade_id
            JOIN ref_sync_statuses rs ON uf.sync_status = rs.sync_status_id
            {where_clause}
        """)

        data_query = text(f"""
            SELECT
                uf.file_id,
                uf.original_filename,
                uf.institution_name,
                uf.upload_timestamp,
                rg.grade_code AS grade,
                uf.row_count,
                uf.is_sync,
                rs.status_code AS sync_status
            FROM uploaded_files uf
            JOIN ref_grades rg ON uf.grade = rg.grade_id
            JOIN ref_sync_statuses rs ON uf.sync_status = rs.sync_status_id
            {where_clause}
            ORDER BY uf.upload_timestamp DESC
            LIMIT :limit
            OFFSET :offset
        """)

        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query).scalar()
            rows = conn.execute(data_query, params).mappings().all()

        return [dict(row) for row in rows], total_rows