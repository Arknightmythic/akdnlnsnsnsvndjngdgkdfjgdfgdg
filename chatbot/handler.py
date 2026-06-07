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

load_dotenv()

MODEL_BASE_URL = os.getenv("MODEL_BASE_URL")
opik_tracer = OpikTracer()

class SynchronoAgent:
    def __init__(self, model: str = "ollama:gemma4:31b-cloud"):
        self._model = init_chat_model(
            model=model,
            base_url="https://ollama.com",
            temperature=0,
            

        )
        self._system_prompt = SystemMessage(SYNCHORNO_AGENT_SYSTEM_PROMPT)
        self._tools = [run_query]

    def ask(self, conversation_id: str, question: str)-> str:
        with SqliteSaver.from_conn_string("chatbot/memory.db") as checkpointer:
            checkpointer.setup()
            agent = create_agent(
                model=self._model,
                system_prompt=self._system_prompt,
                tools=self._tools,
                middleware=[
                    SummarizationMiddleware(
                        model=self._model,
                        trigger=("messages", 20), 
                        keep=("messages", 10)
                    ),
                    ToolRetryMiddleware(),
                ],
                # checkpointer=checkpointer
            )

            response = agent.invoke(
                {"messages": [HumanMessage(question)]},
                config={
                    "callbacks": [opik_tracer],
                    # "configurable": {"thread_id": conversation_id}
                }
            )

            return response["messages"][-1].text