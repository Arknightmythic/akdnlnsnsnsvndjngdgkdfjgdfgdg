"""Test single reasoning dry_run: fetch data via SQL, lalu kirim ke LLM tanpa update DB."""
import os
import sys
import time
import json
import logging
import pytest

logging.basicConfig(level=logging.INFO, format='%(message)s')

from sqlalchemy import create_engine
from dotenv import load_dotenv

from reasoning.reasoning_service import ReasoningService

load_dotenv()

def test_single_reasoning_dry_run(file_id):
    DATABASE_URL = (
        f"mysql+pymysql://"
        f"{os.getenv('STARROCKS_USER')}:"
        f"{os.getenv('STARROCKS_PASSWORD')}@"
        f"{os.getenv('STARROCKS_HOST')}:"
        f"{os.getenv('STARROCKS_PORT')}/"
        f"{os.getenv('STARROCKS_DATABASE')}"
    )
    engine = create_engine(DATABASE_URL)

    print("=== INITIALIZING SERVICE ===")
    # Tidak perlu minio_client lagi — data diambil dari manual_matches via SQL
    service = ReasoningService(engine)

    print(f"\n=== STARTING DRY RUN REASONING FOR FILE {file_id} (LIMIT 1) ===")
    start_time = time.perf_counter()

    result = service.process_reasoning(file_id, dry_run=True, limit=1)

    total_time = time.perf_counter() - start_time

    print("\n=== SUMMARY ===")
    print(json.dumps(result, indent=2))
    print(f"\nTotal Python script execution time: {round(total_time, 2)}s")

    # Simpan hasil ke folder output_tests
    output_dir = os.path.join(os.path.dirname(__file__), "output_tests")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"reasoning_result_{file_id}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Hasil disimpan di: {output_path}")

    # Assertions for Pytest
    assert result is not None, "Result should not be None"

    if result.get("status") == "error":
        pytest.skip(f"Tidak ada data tersedia: {result.get('message', '')}")
    assert result["processed_count"] > 0, "Should process at least 1 row"

    assert len(result["results"]) > 0, "No reasoning result returned"
    first_result = result["results"][0]

    assert "error" not in first_result, f"LLM returned error: {first_result.get('error', '')}"
    assert "reason" in first_result and len(first_result["reason"]) > 0, "LLM should return a valid string reason"
