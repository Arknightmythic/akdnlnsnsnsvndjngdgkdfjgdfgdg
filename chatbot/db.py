from langchain_community.utilities import SQLDatabase
from dotenv import load_dotenv

from ingestion.starrocks_connection import DATABASE_URL

load_dotenv()

db = SQLDatabase.from_uri(DATABASE_URL)