import os
import json
import time
import logging
import math
from celery import Task
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

from reasoning.celery_app import celery_app

load_dotenv()

logger = logging.getLogger(__name__)


def _make_engine():
    return create_engine(
        f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}"
        f"@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}",
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=20,
        max_overflow=10,
    )


class ReasoningTask(Task):
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
    Dispatcher: ambil semua row PENDING lalu pecah ke batch-batch kecil.
    Tidak perlu latency tracking karena task ini hanya query + dispatch,
    bukan eksekusi reasoning yang sesungguhnya.
    """
    from sqlalchemy import text
    try:
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE uploaded_files 
                    SET reasoning_task_status = 'PROCESSING'
                    WHERE file_id = :file_id
                """),
                {"file_id": file_id}
            )
    except Exception as e:
        logger.error(f"Gagal update reasoning_task_status (PROCESSING): {e}")

    try:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id FROM manual_matches WHERE file_id = :f AND reasoning_status = 'PENDING'"),
                {"f": file_id}
            ).fetchall()

        all_ids    = [row[0] for row in rows]
        total_rows = len(all_ids)

        if total_rows == 0:
            # --- UPDATE 4: Jika 0 baris (tidak ada yang manual_review), jadikan SUCCESS ---
            try:
                with self.engine.begin() as conn:
                    conn.execute(
                        text("""
                            UPDATE uploaded_files 
                            SET reasoning_task_status = 'SUCCESS',
                                preview_url = CONCAT('/batch-synchronization/preview?file_id=', :file_id)
                            WHERE file_id = :file_id
                        """),
                        {"file_id": file_id}
                    )
            except Exception:
                pass
                
            return {"status": "success", "file_id": file_id, "queued_batches": 0, "total_rows": 0}

        batch_size    = math.ceil(total_rows / 20) if total_rows > 1000 else 100
        total_batches = math.ceil(total_rows / batch_size)

        queued_batches = 0
        for i in range(0, total_rows, batch_size):
            batch_ids = all_ids[i : i + batch_size]
            queued_batches += 1
            process_batch_reasoning.delay(file_id, batch_ids, queued_batches, total_batches)

        return {
            "status": "success",
            "file_id": file_id,
            "queued_batches": queued_batches,
            "total_rows": total_rows,
            "batch_size": batch_size,
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
    ignore_result=True,
)
def process_batch_reasoning(
    self,
    file_id: str,
    batch_ids: list,
    batch_num: int = 1,
    total_batches: int = 1,
):
    """
    Eksekusi reasoning untuk satu batch manual_matches.
    Latency dicatat per-batch agar bisa dianalisis batch mana yang lambat.
    """
    from audit.audit_service import AuditService

    audit      = AuditService(self.engine)
    start_time = time.time()

    try:
        result     = self.handler.run_reasoning_batch(file_id, batch_ids, batch_num, total_batches)
        latency_ms = int((time.time() - start_time) * 1000)

        if batch_num == total_batches:
            try:
                with self.engine.begin() as conn:
                    conn.execute(
                        text("""
                            UPDATE uploaded_files 
                            SET reasoning_task_status = 'SUCCESS',
                                preview_url = CONCAT('/batch-synchronization/preview?file_id=', :file_id)
                            WHERE file_id = :file_id
                        """),
                        {"file_id": file_id}
                    )
            except Exception as db_exc:
                logger.error(f"Gagal set SUCCESS reasoning batch terakhir {file_id}: {db_exc}")

        audit.log_audit_event(
            actor_org_id="system_auto",
            action="REASONING_BATCH",
            resource_type="FILE",
            resource_id=file_id,
            result="SUCCESS",
            latency_ms=latency_ms,
            after_state=json.dumps({
                "batch_num": batch_num,
                "total_batches": total_batches,
                "batch_size": len(batch_ids),
            }),
        )

        return result

    except Exception as exc:
        latency_ms = int((time.time() - start_time) * 1000)

        # --- UPDATE 6: Jika batch jebol/gagal, tandai sebagai FAILED ---
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text("UPDATE uploaded_files SET reasoning_task_status = 'FAILED' WHERE file_id = :file_id"),
                    {"file_id": file_id}
                )
        except Exception:
            pass
        
        try:
            audit.log_audit_event(
                actor_org_id="system_auto",
                action="REASONING_BATCH",
                resource_type="FILE",
                resource_id=file_id,
                result="FAILED",
                latency_ms=latency_ms,
                after_state=json.dumps({
                    "batch_num": batch_num,
                    "total_batches": total_batches,
                    "batch_size": len(batch_ids),
                    "error": str(exc),
                }),
            )
        except Exception as audit_exc:
            logger.error(
                f"[Reasoning] Gagal catat audit batch {batch_num}/{total_batches} "
                f"file_id={file_id}: {audit_exc}"
            )

        raise self.retry(exc=exc)