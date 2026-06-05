"""Test SQL data fetch and join via manual_matches (tanpa MinIO / DuckDB)."""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from sqlalchemy import create_engine
from dotenv import load_dotenv

from reasoning.reasoning_service import ReasoningService

def test_sql_data_fetch_and_join(file_id):
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

    print(f"\n=== INITIALIZING SERVICE UNTUK FILE_ID: {file_id} ===")
    # Tidak perlu minio — build_comparison_pairs sekarang murni SQL join
    service = ReasoningService(engine)

    # 1. Build Comparison Pairs via SQL JOIN (institution + manual_matches + master)
    print(f"\n[1] Menjalankan SQL JOIN (institution + manual_matches + master)...")
    import pytest
    t0 = time.perf_counter()
    rows, err = service.build_comparison_pairs(file_id, limit=1)
    t1 = time.perf_counter()

    if err:
        pytest.skip(f"Tidak ada data MANUAL_REVIEW untuk file_id {file_id}: {err}")

    assert rows is not None and len(rows) > 0, "Hasil join tidak boleh kosong"
    print(f"[+] Berhasil menggabungkan {len(rows)} baris data dalam {round(t1-t0, 2)} detik!")

    # 2. Verifikasi isi baris pertama
    row = rows[0]
    print(f"\n[2] Menampilkan 1 baris pertama dari hasil join data:")
    print(f"\n--- ID Institution: {row['id']} ---")
    print(f"   Nama Incoming      : {row.get('nama_lengkap')}")
    print(f"   Tempat Lahir       : {row.get('tempat_lahir')}")
    print(f"   Tanggal Lahir      : {row.get('tanggal_lahir')}")
    print(f"   Nama Ibu           : {row.get('nama_ibu')}")
    print(f"   Nama Master        : {row.get('master_nama_lengkap')}")
    print(f"   Tempat Lahir Master: {row.get('master_tempat_lahir')}")

    assert row.get("nama_lengkap") is not None or row.get("master_nama_lengkap") is not None, \
        "Minimal salah satu nama harus ada"

    # Simpan hasil
    output_dir = os.path.join(os.path.dirname(__file__), "output_tests")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"sql_logic_result_{file_id}.txt")

    output_text = f"=== SQL LOGIC TEST: FILE {file_id} ===\n"
    output_text += f"Time to SQL JOIN: {round(t1-t0, 2)}s\n"
    output_text += f"Total Joined Rows: {len(rows)}\n\n"
    output_text += f"--- ID Institution: {row['id']} ---\n"
    output_text += f"   Nama Incoming       : {row.get('nama_lengkap')}\n"
    output_text += f"   Tempat Lahir        : {row.get('tempat_lahir')}\n"
    output_text += f"   Tanggal Lahir       : {row.get('tanggal_lahir')}\n"
    output_text += f"   Nama Ibu            : {row.get('nama_ibu')}\n"
    output_text += f"   Nama Master         : {row.get('master_nama_lengkap')}\n"
    output_text += f"   Tempat Lahir Master : {row.get('master_tempat_lahir')}\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_text)
    print(f"Hasil sampel join disimpan di: {output_path}")

    print("\n[+] Test SQL dan Data Join selesai tanpa memanggil LLM.")
