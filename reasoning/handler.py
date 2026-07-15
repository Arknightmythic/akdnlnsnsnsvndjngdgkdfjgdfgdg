from .reasoning_service import ReasoningService
import concurrent.futures
import json
import redis
import os
from datetime import datetime

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

def push_reasoning_log(file_id: str, message: str, level: str = "INFO"):
    if not file_id: return
    payload = {
        "message": message,
        "level": level,
        "ts": datetime.now().isoformat()
    }
    redis_client.rpush(f"matching_log:{file_id}", json.dumps(payload))
class ReasoningHandler:
    def __init__(self, engine):
        """
        Handler utama untuk orkestrasi reasoning service.
        Hanya membutuhkan engine DB — tidak ada MinIO dependency.
        """
        self.engine = engine
        self.reasoning_service = ReasoningService(engine)

    def run_reasoning_by_id(self, mm_id: int) -> dict:
        """
        Menjalankan AI reasoning untuk satu baris spesifik di manual_matches.
        """
        return self.reasoning_service.process_reasoning_by_id(mm_id=mm_id)

    def test_reasoning(self, file_id: str):
        """Dry run — tidak menyentuh DB, hanya test pipeline data + LLM."""
        print(f"[Reasoning] Dry run for file_id: {file_id}")
        return self.reasoning_service.process_reasoning(file_id, dry_run=True)

    def enqueue_reasoning(self, file_id: str) -> dict:
        """Kirim task orchestrator ke Celery queue."""
        from sqlalchemy import text
        from reasoning.tasks import trigger_rows_for_file
        
        task = trigger_rows_for_file.delay(file_id)
        
        # --- UPDATE 2: Tandai sebagai antrean agar terpantau ---
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE uploaded_files 
                        SET reasoning_task_status = 'QUEUED',
                            reasoning_task_id = :task_id
                        WHERE file_id = :file_id
                    """),
                    {"file_id": file_id, "task_id": task.id}
                )
        except Exception as e:
            print(f"[Reasoning] Gagal set QUEUED status: {e}")
            
        return {"status": "queued", "task_id": task.id, "file_id": file_id}

    def run_reasoning(self, file_id: str) -> dict:
        """Legacy sync run - dialihkan ke enqueue agar aman."""
        return self.enqueue_reasoning(file_id)
    
    def run_reasoning_batch(self, file_id: str, batch_ids: list, batch_num: int = 1, total_batches: int = 1) -> dict:
        """
        Menjalankan AI reasoning secara paralel (Multi-threading) di memori,
        beserta logging status batch ke terminal.
        """
        # Logging Progres
        print(f"🚀 [Batch {batch_num}/{total_batches}] Memulai pemrosesan {len(batch_ids)} baris...")
        
        results_to_update = []
        
        # --- MULTI-THREADING (10 Pekerjaan Sekaligus) ---
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            # Submit semua ID ke executor thread
            futures = {
                executor.submit(
                    self.reasoning_service.process_reasoning_by_id, 
                    mm_id=mm_id, 
                    dry_run=False, 
                    commit_to_db=False
                ): mm_id for mm_id in batch_ids
            }
            
            # Ambil hasil dari thread yang sudah selesai (tanpa mempedulikan urutan)
            for future in concurrent.futures.as_completed(futures):
                try:
                    res = future.result()
                    results_to_update.append(res)
                except Exception as exc:
                    print(f"[ERR] Thread error: {exc}")
                    
        # Setelah semua thread di dalam batch selesai, lakukan Bulk Commit
        if results_to_update:
            self.reasoning_service.bulk_update_mm_results(results_to_update, file_id=file_id)
            
        print(f"✅ [Batch {batch_num}/{total_batches}] Selesai mengeksekusi {len(results_to_update)} baris.")
        
        return {"status": "success", "processed_batch": len(results_to_update)}
