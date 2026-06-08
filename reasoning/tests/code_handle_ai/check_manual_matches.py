import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(
    f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}"
    f"@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}"
)

with engine.connect() as conn:
    res = conn.execute(text("DESCRIBE manual_matches")).fetchall()
    print("TOTAL COLUMNS:", len(res))
    for r in res:
        print(r[0])
