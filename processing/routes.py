from fastapi import APIRouter, UploadFile, File, Request, Header, Depends
from typing import List
from .handler import MatchFileHandler

class MatchFileRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()
        print("Routes initialized")

    def setup_routes(self):
        @self.router.post("/")
        async def process_file(request: Request, file_id: str):
            handler = MatchFileHandler(
                request.app.state.minio_client,
                request.app.state.raw_bucket,
                request.app.state.starrocks_engine
            )
            return await handler.process_file(file_id)
