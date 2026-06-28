from celery import Task
from reasoning.celery_app import celery_app
from sqlalchemy import create_engine
import os
from dotenv import load_dotenv
import math

load_dotenv()

def _make_engine():
    return create_engine(
        f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}"
        f"@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}",
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=20,         # <-- NAIKKAN INI AGAR MULTI-THREADING AMAN
        max_overflow=10,      # <-- TAMBAHKAN OVERFLOW
    )

class ReasoningTask(Task):
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
            from reasoning.handler import ReasoningHandler
            self._handler = ReasoningHandler(self.engine)
        return self._handler

@celery_app.task(
    bind=True,
    base=ReasoningTask,
    name="reasoning.trigger_rows_for_file",
    acks_late=True,
)
def trigger_rows_for_file(self, file_id: str):
    from sqlalchemy import text
    try:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id FROM manual_matches WHERE file_id = :f AND reasoning_status = 'PENDING'"),
                {"f": file_id}
            ).fetchall()
            
        all_ids = [row[0] for row in rows]
        total_rows = len(all_ids)

        if total_rows == 0:
            return {"status": "success", "file_id": file_id, "queued_batches": 0, "total_rows": 0}

        if total_rows > 1000:
            batch_size = math.ceil(total_rows / 20)
        else:
            batch_size = 100

        # --- HITUNG TOTAL BATCH ---
        total_batches = math.ceil(total_rows / batch_size)

        queued_batches = 0
        for i in range(0, total_rows, batch_size):
            batch_ids = all_ids[i : i + batch_size]
            queued_batches += 1
            
            # Lempar nomor batch saat ini dan total batch ke worker
            process_batch_reasoning.delay(file_id, batch_ids, queued_batches, total_batches)
            
        return {
            "status": "success", 
            "file_id": file_id, 
            "queued_batches": queued_batches, 
            "total_rows": total_rows,
            "batch_size": batch_size
        }
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    base=ReasoningTask,
    name="reasoning.process_batch",
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    ignore_result=True
)
def process_batch_reasoning(self, file_id: str, batch_ids: list, batch_num: int = 1, total_batches: int = 1):
    """
    Menerima parameter tambahan batch_num dan total_batches untuk logging.
    """
    try:
        return self.handler.run_reasoning_batch(file_id, batch_ids, batch_num, total_batches)
    except Exception as exc:
        raise self.retry(exc=exc)