from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()
engine = create_engine(
    f"mysql+pymysql://"
    f"{os.getenv('STARROCKS_USER')}:"
    f"{os.getenv('STARROCKS_PASSWORD')}@"
    f"{os.getenv('STARROCKS_HOST')}:"
    f"{os.getenv('STARROCKS_PORT')}/"
    f"{os.getenv('STARROCKS_DATABASE')}"
)

with engine.begin() as conn:
    conn.execute(text("UPDATE institution SET reason = NULL, pattern_name = NULL, reasoning_source = NULL WHERE id = 8466278"))
    print("Institution 8466278 reset!")
