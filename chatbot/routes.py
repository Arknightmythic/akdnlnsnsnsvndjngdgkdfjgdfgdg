from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from chatbot.handler import SynchronoAgent

load_dotenv()

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=2)
    conversation_id: str = Field(..., min_length=2)
    enable_pii: bool = Field(default=True)
    model_name: str = Field(default="ollama:gemma4:31b")
    base_url: str = Field(default="https://ollama.com")

class ChatbotRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup()

    def setup(self):
        @self.router.post("/chat")
        async def chat_agent(request: ChatRequest):
            try:
                if not request.query.strip():
                    raise HTTPException(status_code=400, detail="Empty prompt!")
                
                agent = SynchronoAgent(request.model_name, request.base_url)
                
                return StreamingResponse(
                    agent.stream(request.conversation_id, request.query, request.enable_pii),
                    media_type="text/event-stream"
                )
            except Exception as e:
                print(f"Error: {e}")
                raise HTTPException(status_code=500, detail=str(e))