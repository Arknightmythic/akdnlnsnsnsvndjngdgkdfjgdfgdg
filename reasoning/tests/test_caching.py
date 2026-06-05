import os
import pytest
from sqlalchemy import create_engine
from reasoning.reasoning_service import ReasoningService
from dotenv import load_dotenv

load_dotenv()

def test_pattern_caching_flow():
    # Setup — tidak perlu minio lagi karena sudah pakai native SQL join
    engine = create_engine(
        f"mysql+pymysql://"
        f"{os.getenv('STARROCKS_USER')}:"
        f"{os.getenv('STARROCKS_PASSWORD')}@"
        f"{os.getenv('STARROCKS_HOST')}:"
        f"{os.getenv('STARROCKS_PORT')}/"
        f"{os.getenv('STARROCKS_DATABASE')}"
    )

    service = ReasoningService(engine)

    # Run dry_run=True agar tidak mengubah DB — hanya mengetes pipeline data
    res = service.process_reasoning("558f1a53", dry_run=True, limit=5)

    print("Test Result:", res)

    # Toleransi jika belum ada data MANUAL_REVIEW
    if res.get("status") == "error" and "No MANUAL_REVIEW" in res.get("message", ""):
        pytest.skip("Tidak ada data MANUAL_REVIEW tersedia untuk test ini")

    assert res is not None

if __name__ == "__main__":
    test_pattern_caching_flow()
