import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

def run():
    load_dotenv()
    engine = create_engine(
        f"mysql+pymysql://"
        f"{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}@"
        f"{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/"
        f"{os.getenv('STARROCKS_DATABASE')}"
    )

    with engine.begin() as conn:
        print("Clearing reasoning_patterns cache...")
        conn.execute(text("TRUNCATE TABLE reasoning_patterns"))
        
        print("Resetting all manual_matches COMPLETED status back to PENDING...")
        conn.execute(text("UPDATE manual_matches SET reasoning_status = 'PENDING', reason = NULL, pattern_name = NULL, reasoning_source = NULL WHERE reasoning_status IN ('COMPLETED', 'FAILED')"))
        print("Reset done.")

if __name__ == "__main__":
    run()
