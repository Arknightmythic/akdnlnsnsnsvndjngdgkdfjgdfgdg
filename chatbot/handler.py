from langchain.chat_models import init_chat_model
from langchain.messages import SystemMessage, HumanMessage
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware, ToolRetryMiddleware, TodoListMiddleware
from langgraph.checkpoint.mysql.pymysql import PyMySQLSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from dotenv import load_dotenv
from opik.integrations.langchain import OpikTracer
import os

from chatbot.tools import get_table_names, get_table_detail, run_query
from util.prompts import SYNCHORNO_AGENT_SYSTEM_PROMPT
from ingestion.starrocks_connection import DATABASE_URL
from chatbot.database.starrocks import StarRocksSaver

load_dotenv()

opik_tracer = OpikTracer()

class SynchronoAgent:
    def __init__(self, model: str = "ollama:gemma4:31b"):
        self._model = init_chat_model(
            model=model,
            base_url="https://ollama.com",
            temperature=0,
            

        )
        self._system_prompt = SystemMessage(SYNCHORNO_AGENT_SYSTEM_PROMPT)
        self._tools = [get_table_names, get_table_detail, run_query]
        self._memory = StarRocksSaver(
            url=f"{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}",
            user=os.getenv("STARROCKS_USER"),
            password=os.getenv("STARROCKS_PASSWORD"),
            database=os.getenv("STARROCKS_DATABASE"),

        )
        self._memory.setup()

    def ask(self, conversation_id: str, question: str)-> str:
        agent = create_agent(
                model=self._model,
                system_prompt=self._system_prompt,
                tools=self._tools,
                middleware=[
                    # SummarizationMiddleware(
                    #     model=self._model,
                    #     trigger=("messages", 20), 
                    #     keep=("messages", 10)
                    # ),
                    ToolRetryMiddleware(),
                    TodoListMiddleware()
                ],
                checkpointer=self._memory
            )

        response = agent.invoke(
                {"messages": [HumanMessage(question)]},
                config={
                    "callbacks": [opik_tracer],
                    "configurable": {"thread_id": conversation_id}
                }
            )

        return response["messages"][-1].text
        