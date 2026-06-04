from dotenv import load_dotenv
import re

from chatbot.state import SQLState
from chatbot.db import db

class QueryExecutor:
    def execution_query(state: SQLState)-> SQLState:
        query = state.get("query")
        query = re.sub(r"```(?:sql)?\s*|\s*```|;", '', query, flags=re.IGNORECASE).strip()

        try:
            result = db.run(query)
            if result:
                return {"result": f"Query executed successfully. Result: {result}"}
            else:
                return {"result": "Query executed successfully, but no results returned."}
        except Exception as e:
            return {"error_message": str(e)}