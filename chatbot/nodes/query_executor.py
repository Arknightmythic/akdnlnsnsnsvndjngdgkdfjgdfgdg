from dotenv import load_dotenv
import re

from chatbot.state import ExecutionState
from chatbot.db import db

class QueryExecutor:
    def execution_query(state: ExecutionState)-> ExecutionState:
        query = state.get("query")
        query = re.sub(r"```(?:sql)?\s*|\s*```|;", '', query, flags=re.IGNORECASE).strip()

        try:
            result = db.run(query)
            if result:
                return {"query_result": str(result)}
            else:
                return {"query_result": "No results returned."}
        except Exception as e:
            return {"error_message": str(e)}