import os
import json
import time
import logging
from celery import Task
from sqlalchemy import create_engine
from minio import Minio

from worker import celery_app
from custom_mapping.service import CustomMappingService
from custom_mapping.repository import CustomMappingRepository
from audit.audit_service import AuditService

logger = logging.getLogger(__name__)


def _make_engine():
    return create_engine(
        f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}"
        f"@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}",
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=2,
    )


class CustomMappingTask(Task):
    _engine = None
    _service = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = _make_engine()
        return self._engine

    @property
    def service(self):
        if self._service is None:
            minio_client = Minio(
                os.getenv("MINIO_ENDPOINT"),
                access_key=os.getenv("MINIO_ACCESS_KEY"),
                secret_key=os.getenv("MINIO_SECRET_KEY"),
                secure=False,
            )
            self._service = CustomMappingService(
                engine=self.engine,
                minio_client=minio_client,
                bucket_name=os.getenv("RAW_BUCKET_NAME"),
            )
        return self._service


@celery_app.task(
    bind=True,
    base=CustomMappingTask,
    name="custom_mapping.generate_field_mapping",
    acks_late=True,
)
def generate_field_mapping(self, file_id: str):
    """
    Dipanggil lewat .apply_async(args=[file_id], queue="custom_mapping_queue")
    dari titik mana pun trigger-nya nanti diwire (route tombol 'custom grading',
    atau otomatis setelah grading mendeteksi grade 6). Task ini TIDAK
    mengecek ulang grade/is_custom_ready di sini secara sengaja — validasi itu
    tanggung jawab si trigger, supaya task ini gampang dites terpisah.
    """
    repo = CustomMappingRepository(self.engine)
    audit = AuditService(self.engine)
    start_time = time.time()

    try:
        logger.info(f"Mulai generate custom field mapping untuk file_id: {file_id}")
        result = self.service.generate_mapping(file_id)
        latency_ms = int((time.time() - start_time) * 1000)

        repo.set_custom_mapping_task_info(file_id, self.request.id, "SUCCESS")

        audit.log_audit_event(
            actor_org_id="system_auto",
            action="CUSTOM_MAPPING_GENERATED",
            resource_type="FILE",
            resource_id=file_id,
            result="SUCCESS",
            latency_ms=latency_ms,
            after_state=json.dumps(result),
        )
        return result

    except Exception as exc:
        logger.error(f"Gagal generate custom field mapping untuk {file_id}: {exc}")
        latency_ms = int((time.time() - start_time) * 1000)

        repo.set_custom_mapping_task_info(file_id, None, "FAILED")

        try:
            audit.log_audit_event(
                actor_org_id="system_auto",
                action="CUSTOM_MAPPING_GENERATED",
                resource_type="FILE",
                resource_id=file_id,
                result="FAILED",
                latency_ms=latency_ms,
                after_state=json.dumps({"error": str(exc)}),
            )
        except Exception as audit_exc:
            logger.error(f"Gagal mencatat audit FAILED untuk {file_id}: {audit_exc}")

        raise self.retry(exc=exc, max_retries=2, countdown=30)