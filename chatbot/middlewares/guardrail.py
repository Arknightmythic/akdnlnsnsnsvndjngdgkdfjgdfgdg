from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain.messages import AIMessage, HumanMessage
from langchain_core.prompts import PromptTemplate
from langchain.chat_models import init_chat_model
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field
from typing import Optional
from dotenv import load_dotenv
import os

from chatbot.prompts import PROMPT_INJECTION_GUARDRAIL_PROMPT

load_dotenv()

MODEL_BASE_URL = os.getenv("MODEL_BASE_URL")

class PromptInjectionGuardrailOutput(BaseModel):
    is_dangerous: bool = Field(..., description="security status of the user query")
    reason: Optional[str] = Field(description="reasoning behind the security status")

class PromptInjectionGuardrail(AgentMiddleware):
    def __init__(self):
        self._prompt = PromptTemplate.from_template(PROMPT_INJECTION_GUARDRAIL_PROMPT)
        self._model = init_chat_model(
            model="ollama:gemma4:31b", 
            base_url=MODEL_BASE_URL,
            temperature=0
        ).with_structured_output(PromptInjectionGuardrailOutput)
        self._chain = self._prompt |  self._model

    @hook_config(can_jump_to=["end", "model"])
    def before_agent(self, state: AgentState, runtime: Runtime)-> AgentState:
        messages = state.get("messages")
        message = messages[-1]

        if isinstance(message, HumanMessage) and message:
            try:
                results: PromptInjectionGuardrailOutput = self._chain.invoke({"user_query": message})
                if results.is_dangerous:
                    return {"jump_to": "end", "messages": [AIMessage(results.reason)]}
            except Exception as e:
                return {"jump_to": "end", "messages": [AIMessage("An error occurred while checking the security of your query. Please try again later.")]}
        return {"jump_to": "model"}