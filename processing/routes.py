from fastapi import APIRouter, File, Request, Header, Depends
from starlette import status
from starlette.responses import JSONResponse
from audit.audit_service import AuditService
from .tasks import run_matching_task

class MatchFileRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()
        print("Routes initialized")

    def setup_routes(self):
        @self.router.post("/")
        def process_file(request: Request, file_id: str):
            # Log Access Event tetap dicatat secara sinkron
            client_ip = request.client.host if request.client else "unknown"
            audit_service = AuditService(request.app.state.starrocks_engine)
            audit_service.log_access_event(
                action="ACCESS_MATCH_ENDPOINT",
                resource_type="ENDPOINT",
                resource_id=file_id,
                ip_address=client_ip,
                result="SUCCESS"
            )
            
            # Offload proses berat ke Celery Worker (menggunakan queue spesifik)
            run_matching_task.apply_async(args=[file_id], queue="matching_queue")
            
            # Langsung kembalikan respons 202 ke frontend/client
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "status": "ACCEPTED",
                    "message": "Data matching process has been enqueued and is running in the background.",
                    "file_id": file_id
                }
            )