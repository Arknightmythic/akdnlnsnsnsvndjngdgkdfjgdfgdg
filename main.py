from contextlib import asynccontextmanager

from minio import Minio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os
import uvicorn

from ingestion.routes import UploadFileRoutes
from ingestion.starrocks_connection import engine

from processing.routes import MatchFileRoutes
from retrieval.routes import RetrieveDataRoutes

class SynchronoAPI:
    def __init__(self):
        self.app = FastAPI(lifespan=self._lifespan)

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self.include_routers()

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        print(">>> Starting up ...")

        app.state.minio_client = Minio(
            os.getenv("MINIO_ENDPOINT"),
            access_key=os.getenv("MINIO_ACCESS_KEY"),
            secret_key=os.getenv("MINIO_SECRET_KEY"),
            secure=False
        )

        app.state.raw_bucket = os.getenv("RAW_BUCKET_NAME")

        if not app.state.minio_client.bucket_exists(app.state.raw_bucket):
            app.state.minio_client.make_bucket(app.state.raw_bucket)
        print(">>> MinIO initialized")

        app.state.starrocks_engine = engine
        print(">>> StarRocks connection opened")

        yield

        engine.dispose()
        print(">>> StarRocks connection closed")
        print(">>> Shutting down ...")

    def include_routers(self):
        upload_routes = UploadFileRoutes()
        self.app.include_router(upload_routes.router, prefix="/files")

        match_routes = MatchFileRoutes()
        self.app.include_router(match_routes.router, prefix="/match")

        retrieve_routes = RetrieveDataRoutes()
        self.app.include_router(retrieve_routes.router)

    def run(self):
        uvicorn.run(self.app,host="0.0.0.0",port=9191)

synchrono_api = SynchronoAPI()
app = synchrono_api.app

if __name__ == "__main__":
    synchrono_api.run()