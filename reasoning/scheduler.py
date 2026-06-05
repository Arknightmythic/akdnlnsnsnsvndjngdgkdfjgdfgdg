import time
import threading
from sqlalchemy import text

class ReasoningScheduler:
    def __init__(self, engine, minio_client, bucket_name, handler):
        self.engine = engine
        self.minio_client = minio_client
        self.bucket_name = bucket_name
        self.handler = handler
        
        self._stop_event = threading.Event()
        self._thread = None
        self.poll_interval = 15 # detik
        self.is_running = False

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            print("[Scheduler] Already running.")
            return
            
        self._stop_event.clear()
        self.is_running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        print("[Scheduler] Started.")

    def stop(self):
        if self._thread is not None:
            self._stop_event.set()
            self._thread.join()
            self._thread = None
            self.is_running = False
            print("[Scheduler] Stopped.")

    def status(self):
        return {
            "is_running": self.is_running,
            "poll_interval_seconds": self.poll_interval
        }

    def _get_pending_files(self):
        query = text("""
            SELECT file_id 
            FROM uploaded_files 
            WHERE sync_status = 'Waiting_Action' 
              AND reasoning_status = 'PENDING'
            ORDER BY upload_timestamp ASC
        """)
        with self.engine.connect() as conn:
            return [row["file_id"] for row in conn.execute(query).mappings().all()]

    def _set_reasoning_status(self, file_id: str, status: str):
        query = text("""
            UPDATE uploaded_files
            SET reasoning_status = :status
            WHERE file_id = :file_id
        """)
        with self.engine.begin() as conn:
            conn.execute(query, {"status": status, "file_id": file_id})

    def _poll_loop(self):
        print("[Scheduler] Thread running, waiting for files...")
        while not self._stop_event.is_set():
            try:
                pending_files = self._get_pending_files()
                
                for file_id in pending_files:
                    if self._stop_event.is_set():
                        break
                        
                    print(f"[Scheduler] Found pending file: {file_id}. Processing...")
                    self._set_reasoning_status(file_id, 'PROCESSING')
                    
                    try:
                        # Panggil handler reasoning service
                        result = self.handler.run_reasoning(file_id)
                        
                        if result and result.get("status") == "error":
                            print(f"[Scheduler] Error processing {file_id}: {result.get('message')}")
                            # Bisa set ke FAILED, tapi untuk sekarang kembali ke PENDING agar bisa dicoba lagi 
                            # atau SKIPPED jika memang tidak ada data
                            if "No MANUAL_REVIEW records" in result.get("message", ""):
                                self._set_reasoning_status(file_id, 'SKIPPED')
                            else:
                                self._set_reasoning_status(file_id, 'FAILED')
                        else:
                            print(f"[Scheduler] Completed reasoning for {file_id}")
                            self._set_reasoning_status(file_id, 'COMPLETED')
                            
                    except Exception as e:
                        print(f"[Scheduler] Exception processing {file_id}: {e}")
                        self._set_reasoning_status(file_id, 'FAILED')
            
            except Exception as e:
                print(f"[Scheduler] DB/Query error in poll loop: {e}")
                
            # Sleep 15s using wait() so it can be interrupted by stop_event
            self._stop_event.wait(self.poll_interval)
