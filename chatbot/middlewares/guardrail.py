from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain.messages import AIMessageChunk, HumanMessage
from langchain_core.prompts import PromptTemplate
from langchain.chat_models import init_chat_model
from langchain_openai import ChatOpenAI
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field
from typing import Optional
from dotenv import load_dotenv
import os

from chatbot.prompts import PROMPT_INJECTION_GUARDRAIL_PROMPT
from chatbot.consts import GUARDRAIL_MODEL

load_dotenv()

class PromptInjectionGuardrailOutput(BaseModel):
    is_dangerous: bool = Field(..., description="security status of the user query")
    answer: Optional[str] = Field(default="", description="if the user query is dangerous, provide a safe answer to the user. Otherwise, this field can be left empty if the query is safe.")

class PromptInjectionGuardrail(AgentMiddleware):
    def __init__(self):
        self._prompt = PromptTemplate.from_template(PROMPT_INJECTION_GUARDRAIL_PROMPT)
        self._model = init_chat_model(
            model=GUARDRAIL_MODEL,
            temperature=0,
            base_url=os.getenv("OLLAMA_CLOUD_BASE_URL"),
            api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
            model_provider="openai",
            stream_usage=True
        ).with_structured_output(PromptInjectionGuardrailOutput)
        self._chain = self._prompt |  self._model

    @hook_config(can_jump_to=["end", "model"])
    def before_agent(self, state: AgentState, runtime: Runtime)-> AgentState:
        messages = state.get("messages")
        last_message = messages[-1]

        if isinstance(last_message, HumanMessage) and last_message:
            try:
                results: PromptInjectionGuardrailOutput = self._chain.invoke({"user_query": last_message.text})
                if results.is_dangerous:
                    return {"jump_to": "end", "messages": [AIMessageChunk(results.answer)]}
            except Exception as e:
                print(f"Error in PromptInjectionGuardrail: {e}")
                return {"jump_to": "end", "messages": [AIMessageChunk(f"An error occurred while checking the security of your query. Please try again later. Error: {e}")]}
        return {"jump_to": "model"}