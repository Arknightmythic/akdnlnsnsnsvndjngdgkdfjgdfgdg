from langchain.chat_models import init_chat_model
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import os

from util.prompts import ANSWER_GENERATION_PROMPT

load_dotenv()

MODEL_BASE_URL = os.getenv("MODEL_BASE_URL")

class AnswerGenerationOutput(BaseModel):
    answer: str = Field(description="The generated answer to the user's question based on the query result and the question")

class AnswerGeneration:
    def __init__(self, model: str = "ollama:ministral-3:8b", prompt_template: str = ANSWER_GENERATION_PROMPT):
        self.llm = init_chat_model(
            base_url=MODEL_BASE_URL, 
            model=model,
        ).with_structured_output(AnswerGenerationOutput)

        self.prompt = PromptTemplate.from_template(prompt_template)

    def get_chain(self):
        return self.prompt | self.llm
        