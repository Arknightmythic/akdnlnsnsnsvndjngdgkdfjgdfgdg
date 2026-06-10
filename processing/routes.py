from fastapi import APIRouter, Request
from starlette import status
from starlette.responses import JSONResponse
from audit.audit_service import AuditService
from .tasks import run_matching_task
from processing.repository import StarrocksService

class MatchFileRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()
        print("Routes initialized")

    def setup_routes(self):
        @self.router.post("/")
        def process_file(request: Request, file_id: str):
            client_ip = request.client.host if request.client else "unknown"
            audit_service = AuditService(request.app.state.starrocks_engine)
            audit_service.log_access_event(
                action="ACCESS_MATCH_ENDPOINT",
                resource_type="ENDPOINT",
                resource_id=file_id,
                ip_address=client_ip,
                result="SUCCESS"
            )
            
            # 1. Lempar ke Celery dan dapatkan task_id
            task = run_matching_task.apply_async(args=[file_id], queue="matching_queue")
            
            # 2. Update DB jadi PROCESSING
            starrocks_service = StarrocksService(request.app.state.starrocks_engine)
            starrocks_service.set_matching_task_info(file_id, task.id, "PROCESSING")
            
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "status": "PROCESSING",
                    "message": "Data matching sedang berjalan di background.",
                    "file_id": file_id
                }
            )

        # 3. ENDPOINT BARU UNTUK POLLING FRONTEND
        @self.router.get("/status/{file_id}")
        def get_match_status(request: Request, file_id: str):
            starrocks_service = StarrocksService(request.app.state.starrocks_engine)
            file_data = starrocks_service.get_uploaded_file(file_id)
            
            if not file_data:
                return JSONResponse(status_code=404, content={"message": "File not found"})
                
            return {
                "file_id": file_id,
                "matching_task_status": file_data.get("matching_task_status", "IDLE")
            }