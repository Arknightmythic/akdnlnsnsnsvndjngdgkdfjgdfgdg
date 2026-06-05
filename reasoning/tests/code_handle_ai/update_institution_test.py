import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(
    f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}"
    f"@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}"
)

with engine.begin() as conn:
    print("=== update institution for test ===")
    conn.execute(text("UPDATE institution SET match_result = 2 WHERE file_id = '45b76ab1'"))
    res = conn.execute(text("SELECT COUNT(*) FROM institution WHERE match_result = 2 AND file_id = '45b76ab1'")).fetchall()
    print("Updated rows:", res[0][0])
