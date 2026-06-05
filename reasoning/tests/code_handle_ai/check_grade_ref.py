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

with engine.connect() as conn:
    res = conn.execute(text("SELECT * FROM ref_grades")).mappings().all()
    for r in res:
        print(f"ID: {r['grade_id']} -> Code: {r['grade_code']}")
