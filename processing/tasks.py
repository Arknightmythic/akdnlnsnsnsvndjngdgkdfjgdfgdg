import os
import json
import logging
from celery import Task
from sqlalchemy import create_engine
from minio import Minio
from urllib.parse import urlparse
from redis import Redis as SyncRedis
import time

from worker import celery_app
from processing.handler import MatchFileHandler
from processing.repository import StarrocksService
from retrieval.repository import RetrieveRepository
from audit.audit_service import AuditService

logger = logging.getLogger(__name__)

LOG_TTL_SECONDS = 3600


def _make_engine():
    return create_engine(
        f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}"
        f"@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}",
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=2,
    )


def _make_sync_redis() -> SyncRedis:
    """Buat koneksi Redis synchronous — sama polanya dengan retrieval/tasks.py."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    parsed = urlparse(redis_url)
    return SyncRedis(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        db=int(parsed.path.lstrip("/") or 0),
        password=parsed.password or None,
        decode_responses=True,
    )


def push_log(redis_client: SyncRedis, file_id: str, message: str, level: str = "INFO"):
    """
    Push satu baris log ke Redis list `matching_log:{file_id}`.
    Frontend membaca list ini via SSE endpoint.

    Format payload JSON:
    {
        "message": "Incoming rows: 200000",
        "level"  : "INFO" | "SUCCESS" | "ERROR",
        "ts"     : "<timestamp ISO>"
    }
    """
    import datetime
    payload = json.dumps({
        "message": message,
        "level": level,
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    key = f"matching_log:{file_id}"
    redis_client.rpush(key, payload)
    redis_client.expire(key, LOG_TTL_SECONDS)


class MatchTask(Task):
    _engine  = None
    _handler = None
    _redis   = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = _make_engine()
        return self._engine

    @property
    def redis(self):
        if self._redis is None:
            self._redis = _make_sync_redis()
        return self._redis

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
    redis     = self.redis
    start_time = time.time()

    
    before_state = retrieval.get_matching_status_before(file_id)

    
    push_log(redis, file_id, "Mulai matching untuk file_id: " + file_id)
    push_log(redis, file_id, "Processing data...")

    try:
        logger.info(f"Mulai matching untuk file_id: {file_id}")
        self.handler.matching_service_new.redis  = redis
        self.handler.matching_service_new.file_id_ctx = file_id
        result = self.handler.process_file(file_id)
        latency_ms = int((time.time() - start_time) * 1000)
        starrocks.set_matching_task_info(file_id, self.request.id, "SUCCESS")

        
        push_log(
            redis, file_id,
            f"Task succeeded — matched: {result.get('matched_rows', 0):,} | "
            f"unmatched: {result.get('unmatched_rows', 0):,} | "
            f"manual_review: {result.get('manual_review_rows', 0):,}",
            level="SUCCESS",
        )
        
        push_log(redis, file_id, "__MATCHING_DONE__", level="SUCCESS")

        audit.log_audit_event(
            actor_org_id="system_auto",
            action=f"MATCHING_GRADE_{result.get('grade', 'UNKNOWN')}",
            resource_type="FILE",
            resource_id=file_id,
            result="SUCCESS",
            latency_ms=latency_ms,
            before_state=json.dumps(before_state),
            after_state=json.dumps(result),
        )

        return result

    except Exception as exc:
        logger.error(f"Gagal matching file_id {file_id}: {exc}")

        starrocks.set_matching_task_info(file_id, None, "FAILED")
        push_log(redis, file_id, f"Task FAILED: {exc}", level="ERROR")
        push_log(redis, file_id, "__DONE__", level="ERROR")
        latency_ms = int((time.time() - start_time) * 1000)

        try:
            audit.log_audit_event(
                actor_org_id="system_auto",
                action="MATCHING_TASK_FAILED",
                resource_type="FILE",
                resource_id=file_id,
                result="FAILED",
                latency_ms=latency_ms,
                before_state=json.dumps(before_state),
                after_state=json.dumps({"error": str(exc)}),
            )
        except Exception as audit_exc:
            logger.error(f"Gagal mencatat audit FAILED untuk {file_id}: {audit_exc}")

        raise self.retry(exc=exc, max_retries=3, countdown=60)