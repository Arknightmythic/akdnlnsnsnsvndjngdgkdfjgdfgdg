from langchain.tools import tool
from langchain.messages import HumanMessage
from dotenv import load_dotenv

from chatbot.sql_graph import SQLGraphBuilder

load_dotenv()

sql_graph = SQLGraphBuilder().get_graph_app()

@tool
def ask_database(question: str)-> str:
    """
    This tool answers natural language questions by querying a SQL database. 
    It's designed to retrieve specific information or insights from the database.

    Args:
        question (str): The user's natural language question about the data in the SQL database.
        
    Returns: Combined string question, query, query result, and final answer.
    """

    response = sql_graph.invoke({"question": HumanMessage(question)})

    final_response = f"""
    Question: {question}
    Query: {response.get("query")}
    Query Result: {response.get("result")}
    Final Answer: {response.get("answer")}
    """
    return final_response

