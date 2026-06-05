"""End-to-End Test for a single ID to measure separate fetching and reasoning times."""
import os
import sys
import time
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

from reasoning.reasoning_service import ReasoningService

def test_e2e_by_id(inst_id: int):
    institution_id = inst_id
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

    print(f"=== INITIALIZING SERVICE UNTUK INSTITUTION ID: {institution_id} ===")
    # ReasoningService sekarang hanya butuh engine — tidak perlu minio lagi
    service = ReasoningService(engine)

    # Cek apakah institution_id ada di database
    with engine.connect() as conn:
        raw_row = conn.execute(
            text("SELECT file_id FROM institution WHERE id = :id"),
            {"id": institution_id}
        ).mappings().first()
        if not raw_row:
            import pytest
            pytest.skip(f"Institution ID {institution_id} tidak ditemukan di database")

        file_id = raw_row["file_id"]

    print(f"[+] Ditemukan file_id = {file_id}. Memulai reasoning pipeline...")

    t0 = time.perf_counter()
    # Sekarang build_comparison_pairs langsung via SQL join (tanpa MinIO / DuckDB)
    rows, err = service.build_comparison_pairs(file_id, limit=1)
    fetch_time = time.perf_counter() - t0

    if err:
        import pytest
        pytest.skip(f"Tidak ada data MANUAL_REVIEW untuk file_id {file_id}: {err}")

    assert rows is not None and len(rows) > 0, "Harus ada minimal 1 baris hasil join"

    row = rows[0]
    print(f"[+] Data berhasil di-join dalam {round(fetch_time, 2)}s")
    print(f"    Nama incoming : {row.get('nama_lengkap')}")
    print(f"    Nama master   : {row.get('master_nama_lengkap')}")

    # Simpan hasil ke output_tests
    output_dir = os.path.join(os.path.dirname(__file__), "output_tests")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"e2e_result_{institution_id}.json")

    final_output = {
        "institution_id": institution_id,
        "file_id": file_id,
        "fetch_time_seconds": round(fetch_time, 2),
        "raw_data": {
            "incoming": {
                "nama_lengkap": row.get("nama_lengkap"),
                "tempat_lahir": row.get("tempat_lahir"),
                "tanggal_lahir": str(row.get("tanggal_lahir")),
                "nama_ibu": row.get("nama_ibu")
            },
            "master": {
                "nama_lengkap": row.get("master_nama_lengkap"),
                "tempat_lahir": row.get("master_tempat_lahir"),
                "tanggal_lahir": str(row.get("master_tanggal_lahir")),
                "nama_ibu": row.get("master_nama_ibu")
            }
        }
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2)

    print(f"\n[+] Selesai! Hasil E2E disimpan di: {output_path}")
    print(json.dumps(final_output, indent=2))
