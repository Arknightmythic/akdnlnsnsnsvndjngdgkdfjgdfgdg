from dotenv import load_dotenv

from chatbot.chains.query_repair import QueryRepair
from chatbot.state import SQLState

load_dotenv()

class QueryRepairement:
    def repair_query(state: SQLState)-> SQLState:
        query = state.get("query")
        error_message = state.get("error_messages")
        question = state.get("question")

        query_repair = QueryRepair()
        query_repair_chain = query_repair.get_chain()

        result = query_repair_chain.invoke({
            "query": query,
            "error_message": error_message,
            "question": question
        })

        return {"query": result.fixed_query}