from langchain.agents.middleware import AgentMiddleware, AgentState, _redaction
from langgraph.runtime import Runtime
from dotenv import load_dotenv
from typing import Literal
from hashlib import sha256
import re

load_dotenv()

class PIIMiddleware(AgentMiddleware):
    def __init__(self, pii_type: str, detector: str, strategy: Literal["mask", "redact", "hash"] = "mask"):
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
                elif self._strategy == "hash":
                    last_msg.content = last_msg.content.replace(match, sha256(match.encode).hexdigest()[:8])
                else:
                    raise ValueError(f"Unsupported strategy: {self._strategy}")
        return state