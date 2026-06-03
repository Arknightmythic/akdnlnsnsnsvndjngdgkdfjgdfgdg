from dotenv import load_dotenv

from chatbot.state import SQLState
from chatbot.chains.query_generation import QueryGeneration

load_dotenv()

class QueryGenerator:
    def generate_query(state: SQLState)-> SQLState:
        schema = state["schema"]
        question = state["question"]

        query_generation = QueryGeneration()
        query_chain = query_generation.get_chain()

        result =  query_chain.invoke({
            "schema": schema,
            "question": question
        })

        return {"query": result.query, "error_message": ""}
