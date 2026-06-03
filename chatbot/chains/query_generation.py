from langchain_core.prompts import PromptTemplate
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import os

load_dotenv()

MODEL_BASE_URL = os.getenv("OLLAMA_BASE_URL")

class QueryGenerationOutput(BaseModel):
    query: str = Field(description="The generated")

class QueryGeneration:
    def __init__(self):
        self.llm = ChatOllama(
            base_url=MODEL_BASE_URL, 
            model="qwen3.5:9b"
        ).with_structured_output(QueryGenerationOutput)

        self.prompt = PromptTemplate.from_template(
        """
        You are a helpful assistant that generates MySQL queries based on a given database schema and a question.
        Rules:
        - Include only exiting columns and tables
        - Add appropriate WHERE, GROUP BY, ORDER BY clauses as needed
        - Limit results to 10 rows unless specified otherwisem

        Database Schema:
        {schema}

        Question:
        {question}
        """
        )

    def get_chain(self):
        return self.prompt | self.llm