"""Test SQL JOIN dari manual_matches ke master (tanpa LLM)."""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from sqlalchemy import create_engine
from dotenv import load_dotenv
from reasoning.reasoning_service import ReasoningService

def test_sql_data_fetch_and_join(file_id):
    load_dotenv()
    import pytest

    engine = create_engine(
        f"mysql+pymysql://"
        f"{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}@"
        f"{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/"
        f"{os.getenv('STARROCKS_DATABASE')}"
    )
    service = ReasoningService(engine)

    print(f"\n=== SQL JOIN TEST: manual_matches -> master | file_id: {file_id} ===")
    t0 = time.perf_counter()
    rows, err = service.build_comparison_pairs(file_id, limit=1)
    elapsed = time.perf_counter() - t0

    if err:
        pytest.skip(f"Tidak ada data: {err}")

    assert rows and len(rows) > 0, "Harus ada minimal 1 baris hasil join"
    print(f"[+] JOIN selesai dalam {round(elapsed, 2)}s, dapat {len(rows)} baris")

    row = rows[0]
    print(f"    ID mm         : {row['id']}")
    print(f"    Nama incoming : {row.get('nama_lengkap')}")
    print(f"    Nama master   : {row.get('master_nama_lengkap')}")
    print(f"    TL incoming   : {row.get('tempat_lahir')}")
    print(f"    TL master     : {row.get('master_tempat_lahir')}")

    output_dir = os.path.join(os.path.dirname(__file__), "output_tests")
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, f"sql_logic_result_{file_id}.txt"), "w", encoding="utf-8") as f:
        f.write(f"file_id: {file_id}\n")
        f.write(f"JOIN time: {round(elapsed, 2)}s\n")
        f.write(f"Rows: {len(rows)}\n\n")
        for k, v in row.items():
            f.write(f"  {k:30s}: {v}\n")

    print("[+] Test SQL JOIN selesai tanpa memanggil LLM.")
