from langchain.agents.middleware import AgentMiddleware, AgentState
from langgraph.runtime import Runtime
from dotenv import load_dotenv
import re

load_dotenv()

class PIIMiddlewareSynchrono(AgentMiddleware):
    def __init__(self, detector: str, strategy: str = "mask"):
        self._detector = detector
        self._strategy = strategy

    def after_agent(self, state: AgentState, runtime: Runtime)-> AgentState:
        messages = state.get("messages")
        if not messages:
            return state
        
        last_msg = messages[-1]
        if hasattr(last_msg, "content") and last_msg.content:
            matches = re.findall(self._detector, last_msg.content)
            for match in matches:
                if self._strategy == "mask":
                    last_msg.content = last_msg.content.replace(match, f"{match[:3]}**********{match[-3:]}")
        return state