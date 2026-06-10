
from langchain.chat_models import init_chat_model
from langchain.messages import SystemMessage, HumanMessage, AIMessageChunk
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware, ToolRetryMiddleware, TodoListMiddleware, PIIMiddleware
from dotenv import load_dotenv
from opik.integrations.langchain import OpikTracer
import os
import json
import asyncio

from chatbot.tools import get_table_names, get_table_detail, run_query
from util.chatbot_prompts.prompts import SYNCHORNO_AGENT_SYSTEM_PROMPT
from chatbot.database import StarRocksSaver
from chatbot.middlewares import PIIMiddlewareSynchrono

load_dotenv()

opik_tracer = OpikTracer()

class SynchronoAgent:
    def __init__(self, model: str, base_url: str):
        self._model = init_chat_model(
            model=model,
            base_url=base_url,
            temperature=0,
        )
        self._system_prompt = SystemMessage(SYNCHORNO_AGENT_SYSTEM_PROMPT)
        self._tools = [get_table_names, get_table_detail, run_query]
        self._middleware = [
                    SummarizationMiddleware(
                        model=self._model,
                        trigger=("messages", 30), 
                        keep=("messages", 10)
                    ),
                    ToolRetryMiddleware(),
                    TodoListMiddleware(),
        ]
        self._memory = StarRocksSaver(
            url=f"{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}",
            user=os.getenv("STARROCKS_USER"),
            password=os.getenv("STARROCKS_PASSWORD"),
            database=os.getenv("STARROCKS_DATABASE"),

        )
        self._memory.setup()

    def ask(self, conversation_id: str, question: str, enable_pii: bool = True)-> str:
        _current_middleware = self._middleware.copy()
        if enable_pii:
            _current_middleware.extend([
                PIIMiddlewareSynchrono(pii_type="nik", detector=r"\b\d{16}\b", strategy="mask")
            ])

        _agent = create_agent(
                model=self._model,
                system_prompt=self._system_prompt,
                tools=self._tools,
                middleware=_current_middleware,
                checkpointer=self._memory
            )

        response = _agent.invoke(
                {"messages": [HumanMessage(question)]},
                config={
                    "callbacks": [opik_tracer],
                    "configurable": {"thread_id": conversation_id}
                }
            )
        return response["messages"][-1].text
    
    async def stream(self, conversation_id: str, question: str, enable_pii: bool = True):
        _current_middleware = self._middleware.copy()
        if enable_pii:
            _current_middleware.extend([
                PIIMiddlewareSynchrono(pii_type="nik", detector=r"\b\d{16}\b", strategy="mask")
            ])

        _agent = create_agent(
                model=self._model,
                system_prompt=self._system_prompt,
                tools=self._tools,
                middleware=_current_middleware,
                checkpointer=self._memory
            )
        start_payload = {
            "step": "START",              
            "content": "",           

        }
        yield f"data: {json.dumps(start_payload)}\n\n"

        async for chunk, metadata in _agent.astream(
                {"messages": [HumanMessage(question)]},
                stream_mode="messages",
                config={
                    "callbacks": [opik_tracer],
                    "configurable": {"thread_id": conversation_id}
                }
            ):
            data = {
                "step": chunk.__class__.__name__,
                "content": chunk.text,
            }

            if isinstance(chunk, AIMessageChunk) and chunk.tool_calls:
                data["tool_calls"] = chunk.tool_calls

            yield f"data: {json.dumps(data)}\n\n"

        end_payload = {
            "step": "END",
            "content": "",
        }
        yield f"data: {json.dumps(end_payload)}\n\n"

async def main():
    agent = SynchronoAgent("ollama:gemma4:31b", "https://ollama.com")
    async for data in agent.stream("coba14", "Tampilkan 3 data dari institution beserta NIK-nya."):
        print(data)

if __name__ == "__main__":
    asyncio.run(main())
    