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
                file_id,
                original_filename,
                institution_name,
                upload_timestamp,
                grade,
                row_count,
                processing_status,
                is_sync
            FROM uploaded_files
            ORDER BY upload_timestamp DESC
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