
from langchain.chat_models import init_chat_model
from langchain.messages import SystemMessage, HumanMessage, AIMessageChunk
from langchain_core.prompts import PromptTemplate
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware, ToolRetryMiddleware, TodoListMiddleware
from dotenv import load_dotenv
from opik.integrations.langchain import OpikTracer
from pydantic import BaseModel, Field
import os
import json
import asyncio

from chatbot.tools import get_table_names, get_table_detail, run_query, retrieve
from util.chatbot_prompts.prompts import SYNCHORNO_AGENT_SYSTEM_PROMPT, TITLE_GENERATOR_PROMPT
from chatbot.database import StarRocksSaver, mysql_db as db
from chatbot.middlewares import PIIMiddlewareSynchrono
 
load_dotenv()

opik_tracer = OpikTracer()

class TitleOutput(BaseModel):
    title: str =  Field(description="conversation title generated from user question in Bahasa Indonesia.")
    
class TitleGenerator:
    def __init__(self, model: str, base_url: str):
        self._model = init_chat_model(
            model=model,
            base_url=base_url,
            temperature=0,
            
        ).with_structured_output(TitleOutput)

        self._prompt = PromptTemplate.from_template(TITLE_GENERATOR_PROMPT)
        self._chain = self._prompt | self._model
        
    def generate_title(self, question: str)-> TitleOutput:
        results: TitleOutput = self._chain.invoke({"question": question})
        return results
        
        
class ChatbotHandler:
    def __init__(self, model: str, base_url: str):
        self._model = init_chat_model(
            model=model,
            base_url=base_url,
            temperature=0,
        )
        self._system_prompt = SystemMessage(SYNCHORNO_AGENT_SYSTEM_PROMPT)
        self._tools = [get_table_names, get_table_detail, run_query, retrieve]
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
        self.generator = TitleGenerator(model, base_url)
        self._generator_result = None

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
    
    async def stream(self, user_id: str, conversation_id: str, question: str, enable_pii: bool = True):
        self._update_conversation(user_id=user_id, conversation_id=conversation_id, role="human", content=question)
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

        final_response = ""
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

            if isinstance(chunk, AIMessageChunk) and not chunk.tool_calls:
                final_response += chunk.text
                
            yield f"data: {json.dumps(data)}\n\n"

        end_payload = {
            "step": "END",
            "content": "",
        }
        yield f"data: {json.dumps(end_payload)}\n\n"
        
        if self._generator_result:
            title_payload = {
                "step": "TITLE",
                "content": self._generator_result.title
            }
            yield f"data: {json.dumps(title_payload)}\n\n"
        
        self._update_conversation(user_id=user_id, conversation_id=conversation_id, role="ai", content=final_response)
        
    def _update_conversation(self, user_id: str, conversation_id: str, role: str, content: str):
        if db.conversation_exists(user_id=user_id, conversation_id=conversation_id):
            db.update_conversation_timestamp(conversation_id=conversation_id)
        else:
            print(f"Role: {role}, Content: {content}")
            self._generator_result = self.generator.generate_title(question=content)
            db.insert_conversation(
                conversation_id=conversation_id,
                title=self._generator_result.title,
                user_id=user_id,
            )
        db.insert_message(conversation_id=conversation_id, content=content, role=role)

async def main():
    agent = ChatbotHandler("ollama:gemma4:31b", "https://ollama.com")
    async for data in agent.stream("mausneg","coba14", "Tampilkan 3 data dari institution beserta NIK-nya."):
        print(data)

if __name__ == "__main__":
    asyncio.run(main())
    