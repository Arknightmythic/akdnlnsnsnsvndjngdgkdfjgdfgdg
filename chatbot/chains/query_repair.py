from langchain.chat_models import init_chat_model
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import os 

from util.prompts import QUERY_REPAIR_PROMPT

load_dotenv()

MODEL_BASE_URL = os.getenv("MODEL_BASE_URL")

class QueryRepairOutput(BaseModel):
    fixed_query: str = Field(description="The fixed MySQL query, only SELECT statements are allowed")

class QueryRepair:
    def __init__(self, model: str = "ollama:qwen3.5:9b", prompt_template: str = QUERY_REPAIR_PROMPT):
        self.llm = init_chat_model(
            base_url=MODEL_BASE_URL, 
            model=model,
        ).with_structured_output(QueryRepairOutput)

        self.prompt = PromptTemplate.from_template(prompt_template)


    def get_chain(self):
        return self.prompt | self.llm
        