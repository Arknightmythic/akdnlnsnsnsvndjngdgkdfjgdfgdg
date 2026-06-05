from .reasoning_service import ReasoningService

class ReasoningHandler:
    def __init__(self, engine):
        """
        Handler utama untuk inisialisasi dan orkestrasi reasoning service
        """
        self.engine = engine
        self.reasoning_service = ReasoningService(engine)

    def run_reasoning(self, file_id: str):
        from sqlalchemy import text
        print(f"Running reasoning (DB Update) for file_id: {file_id}")
        
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE uploaded_files SET reasoning_status = 'PROCESSING' WHERE file_id = :fid"), {"fid": file_id})
            
        result = self.reasoning_service.process_reasoning(file_id, dry_run=False)
        
        status = 'COMPLETED' if result.get('status') != 'error' else 'ERROR'
        with self.reasoning_service.engine.begin() as conn:
            conn.execute(text("UPDATE uploaded_files SET reasoning_status = :status WHERE file_id = :fid"), {"status": status, "fid": file_id})
            
        return result

    def test_reasoning(self, file_id: str):
        print(f"Testing reasoning (Dry Run) for file_id: {file_id}")
        return self.reasoning_service.process_reasoning(file_id, dry_run=True)

    def enqueue_reasoning(self, file_id: str) -> dict:
        """Kirim task ke Celery queue (non-blocking, event-driven)."""
        from reasoning.tasks import process_file_reasoning
        task = process_file_reasoning.delay(file_id)
        return {"status": "queued", "task_id": task.id, "file_id": file_id}
