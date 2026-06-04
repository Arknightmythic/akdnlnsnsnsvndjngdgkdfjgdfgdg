from fastapi import APIRouter, UploadFile, File, Request, Form
from fastapi.responses import StreamingResponse
from typing import List
from .handler import UploadFileHandler
from audit.audit_service import AuditService
class UploadFileRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()

    def setup_routes(self):
        @self.router.post("/")
        async def upload_def(request: Request, institution_name: str = Form(...), files: List[UploadFile] = File(...)):
           # Log Access Event
            client_ip = request.client.host if request.client else "unknown"
            audit_service = AuditService(request.app.state.starrocks_engine)
            audit_service.log_access_event(
                action="ACCESS_UPLOAD_ENDPOINT",
                resource_type="ENDPOINT",
                resource_id="/files/",
                ip_address=client_ip,
                result="SUCCESS"
            )

            handler = UploadFileHandler(
                request.app.state.minio_client,
                request.app.state.raw_bucket,
                request.app.state.starrocks_engine
            )
            # Gunakan StreamingResponse dengan media_type event-stream
            return StreamingResponse(
                handler.upload_file_stream(institution_name, files), 
                media_type="text/event-stream"
            )