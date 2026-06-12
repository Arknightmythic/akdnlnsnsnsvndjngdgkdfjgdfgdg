from langchain.tools import tool
from langchain_core.documents import Document
from dotenv import load_dotenv

from chatbot.knowledge import Retriever

load_dotenv()

@tool
def retrieve(query: str, k: int = 5) -> list[Document]:
    """
    A tool used to retrieve cached SQL queries and their answers from Qdrant. 
    It searches for semantically similar questions that have already been answered and cached. 
    Using this tool avoids the need to execute the full SQL generation graph for frequently asked questions.

    Args:
        query (str): The user's specific question or search keywords.
        k (int, optional): The maximum number of cached queries to retrieve. Default is 3.

    Returns:
        list[Document]: A list of RAG result documents. Each document's page_content contains <question>, <answer>, and <query> tags.
    """
    retriever = Retriever()
    results = retriever.hybrid_search(query=query, k=k)
    return results