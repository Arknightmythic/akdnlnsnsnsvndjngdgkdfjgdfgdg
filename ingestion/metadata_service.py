from sqlalchemy import text
from datetime import datetime

class MetadataService:

    def __init__(self, engine):
        self.engine = engine


    def create_uploaded_file(
        self,
        file_id,
        original_filename,
        minio_path
    ):

        query = text("""
            INSERT INTO uploaded_files (
                file_id,
                original_filename,
                minio_path,
                upload_timestamp,
                processing_status
            )
            VALUES (
                :file_id,
                :original_filename,
                :minio_path,
                :upload_timestamp,
                :processing_status
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
                    "processing_status": "UPLOADED"
                }
            )