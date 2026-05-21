from sqlalchemy import text
from datetime import datetime

class MetadataService:

    def __init__(self, engine):
        self.engine = engine


    def create_uploaded_file(
        self,
        file_id,
        original_filename,
        minio_path,
        row_count
    ):

        query = text("""
            INSERT INTO uploaded_files (
                file_id,
                original_filename,
                minio_path,
                upload_timestamp,
                processing_status,
                row_count
            )
            VALUES (
                :file_id,
                :original_filename,
                :minio_path,
                :upload_timestamp,
                :processing_status,
                :row_count
            )
        """)

        with self.engine.begin() as connection:
            connection.execute(
                query,
                {
                    "file_id": file_id,
                    "original_filename": original_filename,
                    "minio_path": minio_path,
                    "upload_timestamp": datetime.utcnow(),
                    "processing_status": "UPLOADED",
                    "row_count": row_count
                }
            )