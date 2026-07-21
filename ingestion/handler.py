import uuid
import io
import os
import json
from datetime import datetime
from typing import List
import time
from dotenv import load_dotenv
from fastapi import UploadFile, File, HTTPException
import polars as pl
import anyio

from audit.audit_service import AuditService
from .metadata_service import MetadataService
from .grader_service import GraderService

load_dotenv()

class UploadFileHandler:
    def __init__(self, minio_client, bucket_name, starrocks_engine):
        self.client = minio_client
        self.bucket_name = bucket_name
        self.metadata_service = MetadataService(starrocks_engine)
        self.grader_service = GraderService(starrocks_engine)
        self.audit_service = AuditService(starrocks_engine)
        print("Upload Handler Initialized")

   
    def _sync_polars_read(self, content):
        return pl.read_csv(io.BytesIO(content))

    def _sync_polars_write(self, df):
        parquet_buffer = io.BytesIO()
        df.write_parquet(parquet_buffer)
        parquet_buffer.seek(0)
        return parquet_buffer

    def _sync_minio_upload(self, bucket_name, object_name, data, length, part_size, content_type):
        self.client.put_object(
            bucket_name=bucket_name,
            object_name=object_name,
            data=data,
            length=length,
            part_size=part_size,
            content_type=content_type
        )

    def _sync_create_metadata(self, file_id, institution_name, original_filename, minio_path, row_count):
        self.metadata_service.create_uploaded_file(
            file_id=file_id,
            institution_name=institution_name,
            original_filename=original_filename,
            minio_path=minio_path,
            row_count=row_count
        )

    def _sync_grade_file(self, file_id, df, minio_path):
        # Menggunakan df.lazy() persis seperti logic asli Anda
        self.grader_service.grade_file(
            file_id=file_id,
            lf=df.lazy(),
            minio_path=minio_path
        )

    def _sync_audit_log(self, actor_org_id, action, resource_type, resource_id, result, latency_ms, after_state):
        self.audit_service.log_audit_event(
            actor_org_id=actor_org_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            latency_ms=latency_ms,
            after_state=after_state
        )
    # =====================================================================

    async def upload_file_stream(self, institution_name: str, files: List[UploadFile]):
        start_time = time.perf_counter()
        
        # Tambahkan parameter opsional 'filename'
        def emit_event(step: str, message: str, filename: str = None):
            payload = {
                # naive local/Jakarta — konsisten dengan timestamp lain di aplikasi
                # ini (lihat BUG_FIXING_GUIDE.md #9)
                "timestamp": datetime.now().strftime("%H:%M:%S"),
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

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = uuid.uuid4().hex[:8]

            # Sisipkan file.filename di argumen ke-3
            yield emit_event("READING", f"Membaca isi file {file.filename}...", file.filename)
            content = await file.read() # Asinkron bawaan FastAPI (Aman)

            # --- 1. Parse CSV (Offload ke Threadpool) ---
            df = await anyio.to_thread.run_sync(self._sync_polars_read, content)
            row_count = len(df)

            # Add column id
            df = df.with_row_index(name="id", offset=1)

            yield emit_event("CONVERTING", f"Konversi ke format Parquet...", file.filename)
            
            # --- 2. Write Parquet (Offload ke Threadpool) ---
            parquet_buffer = await anyio.to_thread.run_sync(self._sync_polars_write, df)

            parquet_object_name = (
                f'{os.getenv("CURATED_BUCKET_NAME")}/'
                f"{timestamp}_{unique_id}_{file.filename.replace('.csv', '.parquet')}"
            )

            yield emit_event("UPLOADING", f"Menyimpan ke MinIO (Curated Zone)...", file.filename)
            
            # --- 3. MinIO Upload (Offload ke Threadpool) ---
            await anyio.to_thread.run_sync(
                self._sync_minio_upload,
                self.bucket_name,
                parquet_object_name,
                parquet_buffer,
                parquet_buffer.getbuffer().nbytes,
                10 * 1024 * 1024,
                "application/x-parquet"
            )

            uploaded_files.append({
                "filename": file.filename,
                "minio_path": parquet_object_name
            })

            yield emit_event("METADATA", f"Menyimpan metadata ke database...", file.filename)
            try:
                # --- 4. DB Metadata Insert (Offload ke Threadpool) ---
                await anyio.to_thread.run_sync(
                    self._sync_create_metadata,
                    unique_id,
                    institution_name,
                    file.filename,
                    parquet_object_name,
                    row_count
                )
            except Exception as e:
                yield emit_event("ERROR", f"Gagal menyimpan metadata: {e}", file.filename)

            yield emit_event("GRADING", f"Melakukan proses Data Grading...", file.filename)
            try:
                # --- 5. Data Grading (Offload ke Threadpool) ---
                await anyio.to_thread.run_sync(
                    self._sync_grade_file,
                    unique_id,
                    df,
                    parquet_object_name
                )

                latency_ms = int((time.perf_counter() - start_time) * 1000)
                
                # --- 6. Audit Log Success (Offload ke Threadpool) ---
                await anyio.to_thread.run_sync(
                    self._sync_audit_log,
                    institution_name,
                    "UPLOAD_AND_GRADE_FILE",
                    "FILE",
                    unique_id,
                    "SUCCESS",
                    latency_ms,
                    json.dumps({"filename": file.filename, "rows": row_count})
                )
            except Exception as e:

                latency_ms = int((time.perf_counter() - start_time) * 1000)
                
                # --- 7. Audit Log Failed (Offload ke Threadpool) ---
                await anyio.to_thread.run_sync(
                    self._sync_audit_log,
                    institution_name,
                    "UPLOAD_AND_GRADE_FILE",
                    "FILE",
                    unique_id,
                    "FAILED",
                    latency_ms,
                    json.dumps({"error": str(e)})
                )
                
                yield emit_event("ERROR", f"Gagal melakukan grading: {e}", file.filename)

            # --- EVENT BARU: Yield spesifik untuk menandakan file ini telah selesai 100% ---
            yield emit_event("DONE_FILE", f"File berhasil diproses dan di-grading.", file.filename)

        yield emit_event("DONE_ALL", "Semua antrean file telah selesai.")