import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from reasoning.handler import ReasoningHandler

class DummyMinio:
    def __init__(self):
        from minio import Minio
        self.client = Minio(
            os.getenv("MINIO_ENDPOINT"),
            access_key=os.getenv("MINIO_ACCESS_KEY"),
            secret_key=os.getenv("MINIO_SECRET_KEY"),
            secure=False
        )
    def get_object(self, *args, **kwargs):
        return self.client.get_object(*args, **kwargs)

load_dotenv()
DATABASE_URL = (
    f"mysql+pymysql://"
    f"{os.getenv('STARROCKS_USER')}:"
    f"{os.getenv('STARROCKS_PASSWORD')}@"
    f"{os.getenv('STARROCKS_HOST')}:"
    f"{os.getenv('STARROCKS_PORT')}/"
    f"{os.getenv('STARROCKS_DATABASE')}"
)
engine = create_engine(DATABASE_URL)
minio_client = DummyMinio()

# Reset state
with engine.begin() as conn:
    conn.execute(text("UPDATE institution SET reason = NULL, pattern_name = NULL, reasoning_source = NULL, match_result = 2 WHERE id = 8466278"))

# Run handler
handler = ReasoningHandler(engine, minio_client, os.getenv("RAW_BUCKET_NAME", "raw"))
handler.run_reasoning("558f1a53")

print("Tabel institution dan uploaded_files berhasil di-update oleh sistem secara real-time!")
