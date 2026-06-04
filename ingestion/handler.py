import uuid
import io
import os
import json
from datetime import datetime, UTC
from typing import List

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

    async def upload_file_stream(self, institution_name: str, files: List[UploadFile]):
        # Tambahkan parameter opsional 'filename'
        def emit_event(step: str, message: str, filename: str = None):
            payload = {
                "timestamp": datetime.now(UTC).strftime("%H:%M:%S"),
                "step": step, 
                "message": message
            }
            if filename:
                payload["filename"] = filename
                
            return f"data: {json.dumps(payload)}\n\n"

        yield emit_event("START", f"Memulai proses untuk {len(files)} file...")
        
        uploaded_files = []

        for file in files:
            if not file.filename.endswith(".csv"):
                yield emit_event("ERROR", f"{file.filename} is not a CSV file", file.filename)
                continue 

            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            unique_id = uuid.uuid4().hex[:8]

            # Sisipkan file.filename di argumen ke-3
            yield emit_event("READING", f"Membaca isi file {file.filename}...", file.filename)
            content = await file.read()

            # Parse CSV once into a DataFrame
            df = pl.read_csv(io.BytesIO(content))
            row_count = len(df)

            # Add column id
            df = df.with_row_index(name="id", offset=1)

            yield emit_event("CONVERTING", f"Konversi ke format Parquet...", file.filename)
            parquet_buffer = io.BytesIO()
            df.write_parquet(parquet_buffer)
            parquet_buffer.seek(0)

            parquet_object_name = (
                f'{os.getenv("CURATED_BUCKET_NAME")}/'
                f"{timestamp}_{unique_id}_{file.filename.replace('.csv', '.parquet')}"
            )

            yield emit_event("UPLOADING", f"Menyimpan ke MinIO (Curated Zone)...", file.filename)
            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=parquet_object_name,
                data=parquet_buffer,
                length=parquet_buffer.getbuffer().nbytes,
                part_size=10 * 1024 * 1024,
                content_type="application/x-parquet"
            )

            uploaded_files.append({
                "filename": file.filename,
                "minio_path": parquet_object_name
            })

            yield emit_event("METADATA", f"Menyimpan metadata ke database...", file.filename)
            try:
                self.metadata_service.create_uploaded_file(
                    file_id=unique_id,
                    institution_name=institution_name,
                    original_filename=file.filename,
                    minio_path=parquet_object_name,
                    row_count=row_count
                )
            except Exception as e:
                yield emit_event("ERROR", f"Gagal menyimpan metadata: {e}", file.filename)

            yield emit_event("GRADING", f"Melakukan proses Data Grading...", file.filename)
            try:
                # Use df.lazy() so the grader doesn't re-parse the data
                self.grader_service.grade_file(
                    file_id=unique_id,
                    lf=df.lazy(),
                    minio_path=parquet_object_name
                )
            except Exception as e:
                yield emit_event("ERROR", f"Gagal melakukan grading: {e}", file.filename)

            # --- EVENT BARU: Yield spesifik untuk menandakan file ini telah selesai 100% ---
            yield emit_event("DONE_FILE", f"File berhasil diproses dan di-grading.", file.filename)

        yield emit_event("DONE_ALL", "Semua antrean file telah selesai.")