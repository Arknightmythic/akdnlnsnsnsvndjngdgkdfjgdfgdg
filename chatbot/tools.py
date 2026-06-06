from langchain.tools import tool
from langchain.messages import HumanMessage
from dotenv import load_dotenv

from chatbot.executor_graph import executor_graph
from chatbot.state import ExecutionState  
from chatbot.db import db
load_dotenv()

@tool
def get_schema() -> str:
    """
    Retrieves the complete database schema, including Data Definition Language (DDL) 
    statements and 3 sample rows for every table. 
    
    You MUST call this tool FIRST before formulating any SQL queries. It is crucial 
    for understanding table structures, column data types, and foreign key 
    relationships (especially for joining with reference tables prefixed with 'ref_').
    """
    schema = db.get_table_info()
    return schema

@tool
def execute_query(query: str) -> dict:
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
    response: ExecutionState = executor_graph.invoke({"query": query})
    return response

if __name__ == "__main__":
    print(get_schema.invoke({}))