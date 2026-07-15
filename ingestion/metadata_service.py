from sqlalchemy import text
from datetime import datetime
from .enums import Process

class MetadataService:

    def __init__(self, engine):
        self.engine = engine


    def create_uploaded_file(
        self,
        file_id,
        institution_name,
        original_filename,
        minio_path,
        row_count
    ):

        query = text("""
            INSERT INTO uploaded_files (
                file_id,
                original_filename,
                institution_name,
                minio_path,
                upload_timestamp,
                processing_status,
                row_count,
                reasoning_task_status,
                investigate_url,
                preview_url
            )
            VALUES (
                :file_id,
                :original_filename,
                :institution_name,
                :minio_path,
                :upload_timestamp,
                :processing_status,
                :row_count,
                'IDLE',
                NULL,
                NULL
            )
        """)

        with self.engine.begin() as connection:
            process = Process.UPLOADED.value
            connection.execute(
                query,
                {
                    "file_id": file_id,
                    "original_filename": original_filename,
                    "institution_name": institution_name,
                    "minio_path": minio_path,
                    "upload_timestamp": datetime.utcnow(),
                    "processing_status": int(process),
                    "row_count": row_count
                }
            )