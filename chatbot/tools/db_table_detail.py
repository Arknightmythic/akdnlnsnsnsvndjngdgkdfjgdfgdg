from langchain.tools import tool
from dotenv import load_dotenv

load_dotenv()

@tool
def get_table_detail(table_name: str)-> str:
    """_summary_

    Args:
        table_name (str): _description_

    Returns:
        str: _description_
    """