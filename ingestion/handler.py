import uuid
import io
import os

from typing import List
from datetime import datetime, UTC
from dotenv import load_dotenv
from fastapi import UploadFile, File, HTTPException
import polars as pl
from .metadata_service import MetadataService
from .grader_service import GraderService

load_dotenv()

class UploadFileHandler:
    def __init__(self, minio_client, bucket_name, starrocks_engine):
        self.client = minio_client
        self.bucket_name = bucket_name
        self.metadata_service = MetadataService(starrocks_engine)
        self.grader_service = GraderService(starrocks_engine)
        print("Upload Handler Initialized")

    async def upload_file(self, institution_name: str, files: List[UploadFile] = File(...)):
        print("Uploading Files...")
        uploaded_files = []

        for file in files:
            if not file.filename.endswith(".csv"):
                raise HTTPException(
                    status_code=400,
                    detail=f"{file.filename} is not a CSV file"
                )

            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            unique_id = uuid.uuid4().hex[:8]

            print("putting object...")
            content = await file.read()

            # Parse CSV once into a DataFrame
            df = pl.read_csv(io.BytesIO(content))
            row_count = len(df)

            # Add column id
            df = df.with_row_index(name="id", offset=1)

            # Convert to Parquet once in memory
            parquet_buffer = io.BytesIO()
            df.write_parquet(parquet_buffer)
            parquet_buffer.seek(0)

            parquet_object_name = (
                f'{os.getenv("CURATED_BUCKET_NAME")}/'
                f"{timestamp}_{unique_id}_{file.filename.replace('.csv', '.parquet')}"
            )

            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=parquet_object_name,
                data=parquet_buffer,
                length=parquet_buffer.getbuffer().nbytes,
                part_size=10 * 1024 * 1024,
                content_type="application/x-parquet"
            )

            print("putting metadata...")

            uploaded_files.append({
                "filename": file.filename,
                "minio_path": parquet_object_name
            })

            try:
                self.metadata_service.create_uploaded_file(
                    file_id=unique_id,
                    institution_name=institution_name,
                    original_filename=file.filename,
                    minio_path=parquet_object_name,
                    row_count=row_count
                )
            except Exception as e:
                print(f"Metadata creation fails for {parquet_object_name}: {e}\n")

            try:
                # Use df.lazy() so the grader doesn't re-parse the data
                self.grader_service.grade_file(
                    file_id=unique_id,
                    lf=df.lazy(),
                    minio_path=parquet_object_name
                )
            except Exception as e:
                print(f"Grading fails for {parquet_object_name}: {e}\n")

        print("Files uploaded!")
        return {
            "message": "Files uploaded successfully",
            "uploaded_files": uploaded_files
        }