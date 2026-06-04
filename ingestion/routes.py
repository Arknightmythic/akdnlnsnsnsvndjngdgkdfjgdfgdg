from fastapi import APIRouter, UploadFile, File, Request, Form
from fastapi.responses import StreamingResponse
from typing import List
from .handler import UploadFileHandler

class UploadFileRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()

    def setup_routes(self):
        @self.router.post("/")
        async def upload_def(request: Request, institution_name: str = Form(...), files: List[UploadFile] = File(...)):
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