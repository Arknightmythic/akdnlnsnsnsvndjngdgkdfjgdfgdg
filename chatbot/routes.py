from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import json
import os

from chatbot.handler import ChatbotHandler
from chatbot.database import mysql_db as db
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

    async def push_audit_to_redis(self, redis_client, event_data: dict):
        await redis_client.rpush("audit_access_logs", json.dumps(event_data))

    def _log_access_async(self, request: Request, background_tasks: BackgroundTasks, action: str, resource_type: str, resource_id: str, actor_user_id: str = "anonymous_poc"):
        event_data = {
            "actor_user_id": actor_user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "ip_address": self._client_ip(request),
            "result": "SUCCESS",
            "latency_ms": 0
        }
        background_tasks.add_task(self.push_audit_to_redis, request.app.state.redis, event_data)

    def setup(self):
        
        @self.router.post("/chat")
        async def chat_agent(
            request: ChatRequest, 
            req: Request, 
            background_tasks: BackgroundTasks
        ):
            try:
                if not request.query.strip():
                    raise HTTPException(status_code=400, detail="Empty prompt!")
                
                
                
                self._log_access_async(
                    request=req,
                    background_tasks=background_tasks,
                    action="SEND_CHAT_MESSAGE",
                    resource_type="CHAT_CONVERSATION",
                    resource_id=request.conversation_id,
                    actor_user_id=request.user_id
                )
                
                agent = ChatbotHandler(request.model_name, request.base_url)
                
                return StreamingResponse(
                    agent.stream(request.user_id, request.conversation_id, request.query, request.enable_pii),
                    media_type="text/event-stream"
                )
            except Exception as e:
                print(f"Error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.router.get("/conversations")
        async def get_conversations(
            user_id: str, 
            req: Request, 
            background_tasks: BackgroundTasks
        ):
            try:
                
                self._log_access_async(
                    request=req,
                    background_tasks=background_tasks,
                    action="VIEW_CHAT_CONVERSATIONS",
                    resource_type="CHAT_LIST",
                    resource_id=user_id,
                    actor_user_id=user_id
                )

                conversations =  db.get_conversations(user_id)
                return conversations    
            except Exception as e:
                print(f"Error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
            
        @self.router.get("/conversations/{conversation_id}")
        async def get_messages(
            conversation_id: str, 
            req: Request, 
            background_tasks: BackgroundTasks
        ):
            try:
                
                self._log_access_async(
                    request=req,
                    background_tasks=background_tasks,
                    action="VIEW_CHAT_MESSAGES",
                    resource_type="CHAT_CONVERSATION",
                    resource_id=conversation_id
                )

                messages = db.get_messages(conversation_id)
                if not messages:
                    raise HTTPException(status_code=404, detail="Messages not found")
                return messages
            except Exception as e:
                print(f"Error: {e}")
                raise HTTPException(status_code=500, detail=str(e))