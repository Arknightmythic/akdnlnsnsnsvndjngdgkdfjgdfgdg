from langchain.agents.middleware import AgentMiddleware, AgentState
from langgraph.runtime import Runtime
from dotenv import load_dotenv
from typing import Literal
import re

load_dotenv()


class PIIMiddleware(AgentMiddleware):
    def __init__(self, pii_type: str, detector: str, strategy: Literal["mask", "redact", "hahs"] = "mask"):
        self._pii_type = pii_type
        self._detector = detector
        self._strategy = strategy
        
    @property
    def name(self)-> str:
        return f"{self.__class__.__name__}[{self._pii_type}]"


    def after_agent(self, state: AgentState, runtime: Runtime)-> AgentState:
        messages = state.get("messages")
        if not messages:
            return state
        
        last_msg = messages[-1]
        if hasattr(last_msg, "content") and last_msg.content:
            matches = re.findall(self._detector, last_msg.content)
            for match in matches:
                if self._strategy == "mask":
                    last_msg.content = last_msg.content.replace(match, f"{'*'*len(match[:-3])}{match[-3:]}")
                elif self._strategy == "redact":
                    last_msg.content = last_msg.content.replace(match, f"[REDACTED]")
        return state