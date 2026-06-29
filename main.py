from contextlib import asynccontextmanager

from minio import Minio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os
import uvicorn

from audit.routes import AuditRoutes
from ingestion.routes import UploadFileRoutes
from ingestion.starrocks_connection import engine

from processing.routes import MatchFileRoutes
from processing.repository import StarrocksService
from reasoning.handler import ReasoningHandler
from reasoning.routes import ReasoningRoutes
from retrieval.routes import RetrieveDataRoutes
from chatbot.routes import ChatbotRoutes
from dotenv import load_dotenv
from reasoning.routes import ReasoningRoutes
from redis.asyncio import Redis

from util.latency_tracker import LatencyTrackingMiddleware

load_dotenv()

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

        self.app.add_middleware(LatencyTrackingMiddleware)

        self.include_routers()

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        print(">>> Starting up ...")

        app.state.redis = Redis.from_url(
            os.getenv("REDIS_URL"),
            decode_responses=True
        )

        print(">>> Redis initialized")

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

        # app.state.reasoning_handler = ReasoningHandler(
        #     app.state.starrocks_engine
            # app.state.minio_client,
            # app.state.raw_bucket
        # )

        starrocks_service = StarrocksService(engine)

        app.state.grade_rules = starrocks_service.load_grade_rules()

        print(f">>> Loaded {len(app.state.grade_rules)} grading rules")

        yield
        await app.state.redis.close()

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

        audit_routes = AuditRoutes()
        self.app.include_router(audit_routes.router, tags=["Audit & Retention"])
        
        chatbot_routes = ChatbotRoutes()
        self.app.include_router(chatbot_routes.router, prefix="/agent", tags=["Chatbot"])
    
        reasoning_routes = ReasoningRoutes()
        self.app.include_router(reasoning_routes.router, prefix="/reasoning")

    def run(self):
        uvicorn.run(self.app,host="0.0.0.0",port=9191)

synchrono_api = SynchronoAPI()
app = synchrono_api.app

if __name__ == "__main__":
    synchrono_api.run()