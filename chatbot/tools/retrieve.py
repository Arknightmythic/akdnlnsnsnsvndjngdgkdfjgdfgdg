from langchain.tools import tool
from langchain_core.documents import Document
from dotenv import load_dotenv

from chatbot.knowledge import Retriever

load_dotenv()

retiever = Retriever()

@tool
def retrieve_data(query: str, k: int = 5)-> list[Document]:
    """_summary_

    Args:
        query (str): _description_
        k (int, optional): _description_. Defaults to 5.

    Returns:
        list[Document]: _description_
    """
    results = retiever.hybrid_search(query=query, k=k)
    return results