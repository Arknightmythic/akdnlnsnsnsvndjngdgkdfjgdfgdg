from langchain.agents.middleware import PIIMiddleware, AgentState
from langgraph.runtime import Runtime
from dotenv import load_dotenv
import re

load_dotenv()

class PIIMiddlewareNIK(PIIMiddleware):
    def __init__(self, pii_type, *, strategy = "mask", detector = None, apply_to_input = True, apply_to_output = False, apply_to_tool_results = False):
        super().__init__(pii_type, strategy=strategy, detector=detector, apply_to_input=apply_to_input, apply_to_output=apply_to_output, apply_to_tool_results=apply_to_tool_results)
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