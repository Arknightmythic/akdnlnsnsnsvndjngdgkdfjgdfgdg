from dotenv import load_dotenv
import re

from chatbot.state import SQLState

load_dotenv()

class QueryValidator:
    def validate_query(state: SQLState)-> SQLState:
        query = state.get("query")
        dangerous_keywords = ["drop", "delete", "update", "insert", "alter", "create", "truncate", "grant", "revoke"]
        
        query = re.sub(r"```(?:sql)?\s*|\s*```", "", query, flags=re.IGNORECASE).strip()
        if any(keyword in query.lower() for keyword in dangerous_keywords):
            return {"result": "[WARNING] The query contains potentially dangerous operations. Only SELECT statements are allowed.", "is_dangerous": True}
        if not query.lower().startswith("select"):
            return {"result": "[WARNING] The query is not a SELECT statement, which is required.", "is_dangerous": True}
        return {"is_dangerous": False}