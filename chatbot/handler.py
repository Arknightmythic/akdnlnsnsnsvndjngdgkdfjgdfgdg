from langchain.chat_models import init_chat_model
from langchain.messages import SystemMessage, HumanMessage
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware, ToolRetryMiddleware, TodoListMiddleware
from langgraph.checkpoint.mysql.pymysql import PyMySQLSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from dotenv import load_dotenv
from opik.integrations.langchain import OpikTracer
import os

from chatbot.tools import ask_database
from util.prompts import SYNCHORNO_AGENT_SYSTEM_PROMPT

load_dotenv()

MODEL_BASE_URL = os.getenv("MODEL_BASE_URL")
opik_tracer = OpikTracer()

class SynchronoAgent:
    def __init__(self, model: str = "ollama:gemma4:e4b"):
        self.model = init_chat_model(
            model=model,
            base_url=MODEL_BASE_URL,
            temperature=0
        )
        self.system_prompt = SystemMessage(SYNCHORNO_AGENT_SYSTEM_PROMPT)
        self.tools = [ask_database]

    def ask(self, conversation_id: str, question: str)-> str:
        with SqliteSaver.from_conn_string("chatbot/memory.db") as checkpointer:
            checkpointer.setup()
            self.agent = create_agent(
                model=self.model,
                system_prompt=self.system_prompt,
                tools=self.tools,
                middleware=[
                    SummarizationMiddleware(
                        model=self.model,
                        trigger=("messages", 20), 
                        keep=("messages", 10)
                    ),
                    ToolRetryMiddleware(),
                    TodoListMiddleware()
                ],
                # checkpointer=checkpointer
            )

            response = self.agent.invoke(
                {"messages": [HumanMessage(question)]},
                config={
                    "callbacks": [opik_tracer],
                    # "configurable": {"thread_id": conversation_id}
                }
            )

            return response["messages"][-1].text
        
if __name__ == "__main__":
    agent = SynchronoAgent()
    answer = agent.ask("session_01", "Field mana yang paling perlu diperbaiki? yg banyak record kosong nya")
    print(answer)