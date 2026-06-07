from langgraph.graph import StateGraph, START, END
from langchain.tools import tool
from typing import TypedDict
from dotenv import load_dotenv
import re

from chatbot.db import db

load_dotenv()

class ExecutionState(TypedDict):
    query: str
    error_message: str
    is_dangerous: bool
    query_result: str

class RunQueryBuilder:
    def __init__(self):
        self._builder = StateGraph(ExecutionState)

        self._builder.add_node("query_validator", self._validate_query) 
        self._builder.add_node("query_executor", self._execution_query) 

        self._builder.add_edge(START, "query_validator")
        self._builder.add_conditional_edges("query_validator", self._is_dangerous, {
            "dangerous": END, 
            "safe": "query_executor"
        })
        self._builder.add_edge("query_executor", END)
        self._graph = self._builder.compile()
        
    def get_graph_app(self):
        return self._graph
        
    def _execution_query(self, state: ExecutionState)-> ExecutionState:
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
        
    def _validate_query(self, state: ExecutionState)-> ExecutionState:
        query = state.get("query")
        dangerous_keywords = ["drop", "delete", "update", "insert", "alter", "create", "truncate", "grant", "revoke"]
        
        query = re.sub(r"```(?:sql)?\s*|\s*```", "", query, flags=re.IGNORECASE).strip()
        if any(keyword in query.lower() for keyword in dangerous_keywords):
            return {"result": "[WARNING] The query contains potentially dangerous operations. Only SELECT statements are allowed.", "is_dangerous": True}
        if not query.lower().startswith("select"):
            return {"result": "[WARNING] The query is not a SELECT statement, which is required.", "is_dangerous": True}
        return {"is_dangerous": False}
        
    def _is_dangerous(self, state: ExecutionState):
        if state.get("is_dangerous"):
            return "dangerous"
        return "safe"

_run_query_graph = RunQueryBuilder().get_graph_app()
        
@tool
def run_query(query: str)-> dict:
    """
    Executes a raw MySQL/StarRocks SELECT query against the database and returns the result.
        
    Args:
        query (str): The strictly READ-ONLY SELECT SQL query to execute. Do NOT wrap the query in markdown formatting (e.g., no ```sql block).
            
    Returns:
        dict: A dictionary containing the query execution state.
            - On success: returns {"result": "...data..."}
            - On execution error: returns {"error_message": "...details..."}. You should analyze this error to correct your query and retry.
            - On dangerous queries (e.g., DROP, UPDATE): returns {"is_dangerous": True, "result": "[WARNING]..."}. You must refuse the operation.
    """
    response: ExecutionState = _run_query_graph.invoke({"query": query})
    return response
