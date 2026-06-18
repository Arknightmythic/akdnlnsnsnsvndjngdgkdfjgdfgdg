import os
import json
import logging
from celery import Task
from sqlalchemy import create_engine
from minio import Minio

from worker import celery_app
from processing.handler import MatchFileHandler
from processing.repository import StarrocksService
from retrieval.repository import RetrieveRepository
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


class MatchTask(Task):
    _engine  = None
    _handler = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = _make_engine()
        return self._engine

    @property
    def handler(self):
        if self._handler is None:
            minio_client      = Minio(
                os.getenv("MINIO_ENDPOINT"),
                access_key=os.getenv("MINIO_ACCESS_KEY"),
                secret_key=os.getenv("MINIO_SECRET_KEY"),
                secure=False,
            )
            raw_bucket        = os.getenv("RAW_BUCKET_NAME")
            starrocks_service = StarrocksService(self.engine)
            grade_rules       = starrocks_service.load_grade_rules()
            self._handler     = MatchFileHandler(
                minio_client=minio_client,
                bucket_name=raw_bucket,
                starrocks_engine=self.engine,
                grade_rules=grade_rules,
            )
        return self._handler


@celery_app.task(
    bind=True,
    base=MatchTask,
    name="processing.run_matching_task",
    acks_late=True,
)
def run_matching_task(self, file_id: str):
    audit     = AuditService(self.engine)
    retrieval = RetrieveRepository(self.engine)
    starrocks = StarrocksService(self.engine)

    # BEFORE_STATE: ambil status file sebelum proses matching dimulai.
    # Ini dilakukan di luar try/except agar state yang ter-capture adalah
    # kondisi SEBELUM apapun diubah, bukan state di tengah proses.
    before_state = retrieval.get_matching_status_before(file_id)

    try:
        logger.info(f"Mulai matching untuk file_id: {file_id}")
        result = self.handler.process_file(file_id)

        starrocks.set_matching_task_info(file_id, self.request.id, "SUCCESS")

        audit.log_audit_event(
            actor_org_id="system_auto",
            action=f"MATCHING_GRADE_{result.get('grade', 'UNKNOWN')}",
            resource_type="FILE",
            resource_id=file_id,
            result="SUCCESS",
            before_state=json.dumps(before_state),
            after_state=json.dumps(result),
        )

        return result

    except Exception as exc:
        logger.error(f"Gagal matching file_id {file_id}: {exc}")

        starrocks.set_matching_task_info(file_id, None, "FAILED")

        # before_state sudah di-fetch sebelum try, jadi tetap akurat
        # meski error terjadi di tengah jalan
        try:
            audit.log_audit_event(
                actor_org_id="system_auto",
                action="MATCHING_TASK_FAILED",
                resource_type="FILE",
                resource_id=file_id,
                result="FAILED",
                before_state=json.dumps(before_state),
                after_state=json.dumps({"error": str(exc)}),
            )
        except Exception as audit_exc:
            logger.error(f"Gagal mencatat audit FAILED untuk {file_id}: {audit_exc}")

        raise self.retry(exc=exc, max_retries=3, countdown=60)