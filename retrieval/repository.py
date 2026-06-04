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