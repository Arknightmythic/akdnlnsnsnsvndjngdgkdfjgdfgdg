import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

def check():
    load_dotenv()
    engine = create_engine(
        f"mysql+pymysql://"
        f"{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}@"
        f"{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/"
        f"{os.getenv('STARROCKS_DATABASE')}"
    )

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT reasoning_status, count(*) as c FROM manual_matches GROUP BY reasoning_status")).mappings().all()
        print("Status manual_matches saat ini:")
        for r in rows:
            print(f"- {r['reasoning_status']}: {r['c']}")

if __name__ == "__main__":
    check()
