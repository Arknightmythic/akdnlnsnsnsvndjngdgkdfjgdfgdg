from langchain_core.prompts import PromptTemplate
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import os

from util.prompts import QUERY_GENERATION_PROMPTS

load_dotenv()

MODEL_BASE_URL = os.getenv("MODEL_BASE_URL")

class QueryGenerationOutput(BaseModel):
    query: str = Field(description="The generated")

class QueryGeneration:
    def __init__(self, model: str = "ollama:ministral-3:8b", prompt_template: str = QUERY_GENERATION_PROMPTS):
        self.llm = init_chat_model(
            base_url=MODEL_BASE_URL, 
            model=model,
        ).with_structured_output(QueryGenerationOutput)

        self.prompt = PromptTemplate.from_template(prompt_template)

    def get_chain(self):
        return self.prompt | self.llm