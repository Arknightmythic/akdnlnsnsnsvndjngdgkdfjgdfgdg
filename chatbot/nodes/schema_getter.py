from dotenv import load_dotenv

from chatbot.state import SQLState
from chatbot.db import db

load_dotenv()

class SchemaGetter:
    def get_schema(state: SQLState)-> SQLState:
        schema = db.get_table_info()
        return {"schema": schema}