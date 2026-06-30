from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import json
import json
import os
import time

from chatbot.handler import ChatbotHandler
from chatbot.database import mysql_db as db
from audit.writer import AuditWriter
from chatbot.consts import CHATBOT_MODEL

load_dotenv()


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=2)
    conversation_id: str = Field(..., min_length=2)
    user_id: str = Field(..., min_length=2)
    enable_pii: bool = Field(default=True)
    model_name: str = Field(default=CHATBOT_MODEL)
    base_url: str = Field(default=os.getenv("OLLAMA_CLOUD_BASE_URL"))

class ChatbotRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup()

    def _client_ip(self, request: Request) -> str:
        return request.client.host if request.client else "unknown"

    # FIX #6: Konsisten dengan retrieval/routes.py — pakai AuditWriter.log_access_async
    # yang punya fallback ke DB jika Redis gagal.
    async def _log_access(
        self,
        request: Request,
        background_tasks: BackgroundTasks,
        action: str,
        resource_type: str,
        resource_id: str,
        actor_user_id: str = "anonymous_poc",
        latency_ms: int = 0
    ):
        writer = AuditWriter(
            engine=request.app.state.starrocks_engine,
            redis=request.app.state.redis,
        )
        background_tasks.add_task(
            writer.log_access_async,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=self._client_ip(request),
            result="SUCCESS",
            latency_ms=latency_ms,
            actor_user_id=actor_user_id,
        )

    def setup(self):

        @self.router.post("/chat")
        async def chat_agent(
            request: ChatRequest,
            req: Request,
            background_tasks: BackgroundTasks,
        ):
            try:
                if not request.query.strip():
                    raise HTTPException(status_code=400, detail="Empty prompt!")

                start_time = time.time()
                agent = ChatbotHandler(request.model_name, request.base_url)
                
                # Hitung latency setup (sebelum stream dimulai)
                latency_ms = int((time.time() - start_time) * 1000)

                await self._log_access(
                    request=req,
                    background_tasks=background_tasks,
                    action="SEND_CHAT_MESSAGE",
                    resource_type="CHAT_CONVERSATION",
                    resource_id=request.conversation_id,
                    actor_user_id=request.user_id,
                    latency_ms=latency_ms,
                )

                return StreamingResponse(
                    agent.stream(
                        request.user_id,
                        request.conversation_id,
                        request.query,
                        request.enable_pii,
                    ),
                    media_type="text/event-stream",
                )
            except Exception as e:
                print(f"Error: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.router.get("/conversations")
        async def get_conversations(
            user_id: str,
            req: Request,
            background_tasks: BackgroundTasks,
        ):
            try:
                start_time = time.time()
                conversations = db.get_conversations(user_id)
                latency_ms = int((time.time() - start_time) * 1000)
                await self._log_access(
                    request=req,
                    background_tasks=background_tasks,
                    action="VIEW_CHAT_CONVERSATIONS",
                    resource_type="CHAT_LIST",
                    resource_id=user_id,
                    actor_user_id=user_id,
                    latency_ms=latency_ms,
                )
                return conversations
            except Exception as e:
                print(f"Error: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.router.get("/conversations/{conversation_id}")
        async def get_messages(
            conversation_id: str,
            req: Request,
            background_tasks: BackgroundTasks,
        ):
            try:
                start_time = time.time()
                messages = db.get_messages(conversation_id)
                latency_ms = int((time.time() - start_time) * 1000)

                await self._log_access(
                    request=req,
                    background_tasks=background_tasks,
                    action="VIEW_CHAT_MESSAGES",
                    resource_type="CHAT_CONVERSATION",
                    resource_id=conversation_id,
                    latency_ms=latency_ms,
                )
                if not messages:
                    raise HTTPException(status_code=404, detail="Messages not found")
                return messages
            except Exception as e:
                print(f"Error: {e}")
                raise HTTPException(status_code=500, detail=str(e))