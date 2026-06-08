import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(
    f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}"
    f"@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}"
)

with engine.connect() as conn:
    print("=== manual_matches ===")
    res = conn.execute(text("SELECT file_id, id_incoming FROM manual_matches LIMIT 5")).fetchall()
    for r in res:
        print(r)
