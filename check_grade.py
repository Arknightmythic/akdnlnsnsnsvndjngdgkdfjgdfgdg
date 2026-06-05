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
    res = conn.execute(text("SELECT grade, minio_path FROM uploaded_files WHERE file_id = '558f1a53'")).mappings().first()
    print(dict(res))
