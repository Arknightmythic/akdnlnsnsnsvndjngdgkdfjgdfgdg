from langchain.tools import tool
from dotenv import load_dotenv

from chatbot.database import mysql_db as db

load_dotenv()


@tool
def get_table_detail(table_name: str) -> str:
    """Return the DDL and sample data for a specific table.

    Args:
        table_name (str): The exact name of the table whose schema and sample
            rows should be retrieved.

    Returns:
        str: A formatted string that contains:
            * ``### TABLE <name> DDL`` – the ``CREATE TABLE`` statement.
            * ``### SAMPLE DATA`` – a tab‑separated preview of up to three
              rows from the table.
        The format is designed for easy consumption by the LLM and for
        downstream rendering (e.g., Markdown tables) when the result is shown
        to the user.
    """
    result = db.get_table_schema(table_name)
    return result