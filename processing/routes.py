from fastapi import APIRouter, UploadFile, File, Request, Header, Depends
from typing import List
from .handler import MatchFileHandler
from audit.audit_service import AuditService

class MatchFileRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()
        print("Routes initialized")

    def setup_routes(self):
        @self.router.post("/")
        async def process_file(request: Request, file_id: str):
            # Log Access Event
            client_ip = request.client.host if request.client else "unknown"
            audit_service = AuditService(request.app.state.starrocks_engine)
            audit_service.log_access_event(
                action="ACCESS_MATCH_ENDPOINT",
                resource_type="ENDPOINT",
                resource_id=file_id,
                ip_address=client_ip,
                result="SUCCESS"
            )
            handler = MatchFileHandler(
                request.app.state.minio_client,
                request.app.state.raw_bucket,
                request.app.state.starrocks_engine
            )
            return await handler.process_file(file_id)
