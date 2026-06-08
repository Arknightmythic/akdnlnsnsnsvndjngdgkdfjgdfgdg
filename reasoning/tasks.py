from celery import Task
from reasoning.celery_app import celery_app
from sqlalchemy import create_engine
import os
from dotenv import load_dotenv

load_dotenv()

def _make_engine():
    return create_engine(
        f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}"
        f"@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}",
        pool_pre_ping=True,       # Check connection before use
        pool_recycle=1800,        # Recycle connections every 30 minutes
        pool_size=2,              # Small pool per worker
    )

class ReasoningTask(Task):
    """Custom Task class with lazy-initialization for DB."""
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
    """
    Orchestrator Task: Query DB for pending rows and fan-out to process_row.
    Berjalan di background agar API FastAPI tidak hang saat meloop jutaan data.
    """
    from sqlalchemy import text
    try:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id FROM manual_matches WHERE file_id = :f AND reasoning_status = 'PENDING'"),
                {"f": file_id}
            ).fetchall()
            
        for row in rows:
            process_row_reasoning.delay(row[0])
            
        return {"status": "success", "file_id": file_id, "queued": len(rows)}
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    base=ReasoningTask,
    name="reasoning.process_row",
    max_retries=3,
    default_retry_delay=60,   # Retry after 60 seconds
    acks_late=True,
)
def process_row_reasoning(self, mm_id: int):
    """
    Celery Task: Run reasoning for a single row in manual_matches.
    """
    try:
        return self.handler.run_reasoning_by_id(mm_id)
    except Exception as exc:
        raise self.retry(exc=exc)
