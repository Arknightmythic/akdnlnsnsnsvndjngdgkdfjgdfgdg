from .reasoning_service import ReasoningService

class ReasoningHandler:
    def __init__(self, engine, minio_client, bucket_name):
        self.reasoning_service = ReasoningService(engine, minio_client, bucket_name)
        print("Reasoning Handler Initialized")

    def run_reasoning(self, file_id: str):
        from sqlalchemy import text
        print(f"Running reasoning (DB Update) for file_id: {file_id}")
        
        with self.reasoning_service.engine.begin() as conn:
            conn.execute(text("UPDATE uploaded_files SET reasoning_status = 'PROCESSING' WHERE file_id = :fid"), {"fid": file_id})
            
        result = self.reasoning_service.process_reasoning(file_id, dry_run=False)
        
        status = 'COMPLETED' if result.get('status') != 'error' else 'ERROR'
        with self.reasoning_service.engine.begin() as conn:
            conn.execute(text("UPDATE uploaded_files SET reasoning_status = :status WHERE file_id = :fid"), {"status": status, "fid": file_id})
            
        return result

    def test_reasoning(self, file_id: str):
        print(f"Testing reasoning (Dry Run) for file_id: {file_id}")
        return self.reasoning_service.process_reasoning(file_id, dry_run=True)
