from fastapi import APIRouter, UploadFile, File, Request, Header, Form, Depends
from typing import List
from .handler import UploadFileHandler

class UploadFileRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()
        print("Routes initialized")

    def setup_routes(self):
        @self.router.post("/")
        async def upload_def(request: Request, institution_name: str = Form(...), files: List[UploadFile] = File(...)):
            handler = UploadFileHandler(
                request.app.state.minio_client,
                request.app.state.raw_bucket,
                request.app.state.starrocks_engine
            )
            return await handler.upload_file(institution_name, files)
