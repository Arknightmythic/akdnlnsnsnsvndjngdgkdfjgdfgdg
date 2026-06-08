from langchain.tools import tool
from dotenv import load_dotenv

from chatbot.database import mysql_db as db

load_dotenv()


@tool
def get_table_names() -> list[str]:
    """Return a list of all table names in the database.

    The underlying ``MySQLDatabase.get_table_names`` method executes a ``SHOW
    TABLES`` statement and returns a plain ``list`` of table identifiers.  The
    returned value is suitable for presentation to the user (e.g. in a Markdown
    list) or for the agent to decide which table's schema it needs to fetch
    with ``get_table_detail``.

    Returns:
        list[str]: A list containing the name of each table in the current
        database schema.
    """
    results = db.get_table_names()
    # ``db.get_table_names`` already returns ``list[str]``; we simply forward it.
    return results