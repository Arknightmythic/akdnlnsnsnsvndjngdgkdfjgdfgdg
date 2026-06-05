import os
import pytest
from sqlalchemy import create_engine
from reasoning.reasoning_service import ReasoningService
from dotenv import load_dotenv
from minio import Minio

load_dotenv()

def test_pattern_caching_flow():
    # Setup
    engine = create_engine(
        f"mysql+pymysql://"
        f"{os.getenv('STARROCKS_USER')}:"
        f"{os.getenv('STARROCKS_PASSWORD')}@"
        f"{os.getenv('STARROCKS_HOST')}:"
        f"{os.getenv('STARROCKS_PORT')}/"
        f"{os.getenv('STARROCKS_DATABASE')}"
    )
    
    minio_client = Minio(
        os.getenv("MINIO_ENDPOINT"),
        access_key=os.getenv("MINIO_ACCESS_KEY"),
        secret_key=os.getenv("MINIO_SECRET_KEY"),
        secure=False
    )
    
    bucket_name = os.getenv("RAW_BUCKET_NAME")
    
    service = ReasoningService(engine, minio_client, bucket_name)
    
    # Run test mode (dry_run=True) on a file ID, maybe 558f1a53
    # Ini tidak akan hit LLM jika kita tidak mau, karena dry_run
    res = service.process_reasoning("558f1a53", dry_run=True, limit=5)
    
    print("Test Result:", res)

if __name__ == "__main__":
    test_pattern_caching_flow()
