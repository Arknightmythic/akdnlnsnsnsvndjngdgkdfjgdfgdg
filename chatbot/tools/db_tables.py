from langchain.tools import tool
from dotenv import load_dotenv

load_dotenv()

@tool
def get_table_names()-> str:
    """_summary_

    Returns:
        str: _description_
    """