import os
import logging
from celery import Task
from sqlalchemy import create_engine
from minio import Minio
import asyncio

from worker import celery_app
from processing.handler import MatchFileHandler
from processing.repository import StarrocksService

logger = logging.getLogger(__name__)

def _make_engine():
    """Membuat koneksi DB baru khusus untuk worker thread"""
    return create_engine(
        f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}"
        f"@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}",
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=2,
    )

class MatchTask(Task):
    """Custom Task untuk inisialisasi resources secara lazy-load"""
    _engine = None
    _handler = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = _make_engine()
        return self._engine

    @property
    def handler(self):
        if self._handler is None:
            # 1. Setup MinIO Client
            minio_client = Minio(
                os.getenv("MINIO_ENDPOINT"),
                access_key=os.getenv("MINIO_ACCESS_KEY"),
                secret_key=os.getenv("MINIO_SECRET_KEY"),
                secure=False
            )
            raw_bucket = os.getenv("RAW_BUCKET_NAME")

            # 2. Setup StarRocks Services & Ambil Rules
            starrocks_service = StarrocksService(self.engine)
            grade_rules = starrocks_service.load_grade_rules()

            # 3. Setup Handler Utama
            self._handler = MatchFileHandler(
                minio_client=minio_client,
                bucket_name=raw_bucket,
                starrocks_engine=self.engine,
                grade_rules=grade_rules
            )
        return self._handler

@celery_app.task(
    bind=True,
    base=MatchTask,
    name="processing.run_matching_task",
    acks_late=True,
)
def run_matching_task(self, file_id: str):
    """
    Background Task untuk mengeksekusi komputasi Matching.
    """
    try:
        logger.info(f"Mulai mengeksekusi proses matching di background untuk file_id: {file_id}")
        # Eksekusi fungsi utama
        result = asyncio.run(self.handler.process_file(file_id))
        logger.info(f"Matching selesai untuk file_id: {file_id}")
        return result
    except Exception as exc:
        logger.error(f"Gagal melakukan matching pada file_id {file_id}: {exc}")
        # Retry otomatis jika terjadi kegagalan (misal: koneksi DB putus sementara)
        raise self.retry(exc=exc, max_retries=3, countdown=60)