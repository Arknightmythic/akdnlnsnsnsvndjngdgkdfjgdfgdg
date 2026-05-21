import uuid
import io

from typing import List
from datetime import datetime
from dotenv import load_dotenv
from fastapi import UploadFile, File, HTTPException
from .metadata_service import MetadataService
from .grader_service import GraderService

load_dotenv()

class UploadFileHandler:
    def __init__(self, minio_client, bucket_name, starrocks_engine):
        self.client = minio_client
        self.bucket_name = bucket_name
        self.metadata_service = MetadataService(starrocks_engine)
        self.grader_service = GraderService(starrocks_engine)
        print("Handler Initialized")

    async def upload_file(self, files: List[UploadFile] = File(...)):
        uploaded_files = []

        for file in files:
            if not file.filename.endswith(".csv"):
                raise HTTPException(
                    status_code=400,
                    detail=f"{file.filename} is not a CSV file"
                )

            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            unique_id = uuid.uuid4().hex[:8]

            object_name = (
                f"incoming/"
                f"{timestamp}_{unique_id}_{file.filename}"
            )

            content = await file.read()

            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                data=io.BytesIO(content),
                length=len(content),
                part_size=10 * 1024 * 1024,
                content_type="text/csv"
            )       

            uploaded_files.append({
                "filename": file.filename,
                "minio_path": object_name
            })

            try:
                self.metadata_service.create_uploaded_file(
                    file_id=unique_id,
                    original_filename=file.filename,
                    minio_path=object_name
                )
            except Exception as e:
                print(f"Metadata creation fails for {object_name}: {e}\n")


            try:
                self.grader_service.grade_file(
                    file_id=unique_id,
                    file_to_be_graded=io.BytesIO(content),
                    minio_path=object_name
                )
            except Exception as e:
                print(f"Grading fails for {object_name}: {e}\n")

        return {
            "message": "Files uploaded successfully",
            "uploaded_files": uploaded_files
        }