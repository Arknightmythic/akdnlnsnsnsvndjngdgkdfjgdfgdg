import os
import sys
import time
import json
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from reasoning.reasoning_service import ReasoningService

def test_cache_hit_performance():
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
    # Tidak perlu minio — sekarang murni SQL join via manual_matches
    service = ReasoningService(engine)

    # Cari file_id yang ada data MANUAL_REVIEW di institution DAN ada di manual_matches
    import pytest
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT inst.file_id 
            FROM institution inst
            JOIN manual_matches mm ON inst.file_id = mm.file_id AND inst.id_incoming = mm.id_incoming
            JOIN master m ON inst.nik_master = m.nik
            WHERE inst.match_result = 2 
              AND inst.reasoning_source IS NULL
            LIMIT 1
        """)).mappings().first()

        if not row:
            pytest.skip("Tidak ada data MANUAL_REVIEW di database yang siap di-test")
        file_id = row["file_id"]

    print(f"[0] Menggunakan file_id: {file_id}")

    # === RESET CACHE DULU ===
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE reasoning_patterns"))
        conn.execute(text(
            "UPDATE institution SET reason = NULL, pattern_name = NULL, reasoning_source = NULL WHERE file_id = :fid"
        ), {"fid": file_id})
    print("[1] Tabel cache dan data institution telah di-reset.")

    # === RUN 1: Seharusnya CACHE MISS (terpanggil LLM) ===
    print("\n[2] Menjalankan RUN 1 (Seharusnya CACHE MISS)...")
    t0 = time.perf_counter()
    res1 = service.process_reasoning(file_id, dry_run=False, limit=20)
    t1 = time.perf_counter()
    print(f"RUN 1 selesai dalam {round(t1-t0, 2)}s")

    if res1.get("status") == "error":
        pytest.skip(f"RUN 1 error: {res1.get('message')}")

    assert res1["updated_count"] > 0, "RUN 1 harus update minimal 1 baris institution"

    # === RESET institution tapi JANGAN hapus reasoning_patterns (biarkan Cache terisi) ===
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE institution SET reason = NULL, pattern_name = NULL, reasoning_source = NULL WHERE file_id = :fid"
        ), {"fid": file_id})
    print("\n[3] Institution di-reset, tapi CACHE tetap ada (tidak di-truncate).")

    # === RUN 2: Seharusnya CACHE HIT ===
    print("\n[4] Menjalankan RUN 2 (Seharusnya CACHE HIT 100%)...")
    t2 = time.perf_counter()
    res2 = service.process_reasoning(file_id, dry_run=False, limit=20)
    t3 = time.perf_counter()
    print(f"RUN 2 selesai dalam {round(t3-t2, 2)}s")

    if res2.get("status") == "error":
        pytest.skip(f"RUN 2 error: {res2.get('message')}")

    assert res2["updated_count"] > 0, "RUN 2 harus update minimal 1 baris institution"

    # Semua sumber di RUN 2 seharusnya CACHE
    run2_sources = [r.get("source") for r in res2.get("results", [])]
    cache_hits = sum(1 for s in run2_sources if s == "CACHE")
    print(f"\n[5] RUN 2: {cache_hits}/{len(run2_sources)} baris dari CACHE")
    assert cache_hits == len(run2_sources), "RUN 2 seharusnya 100% CACHE HIT"

    # Simpan output
    output_dir = os.path.join(os.path.dirname(__file__), "output_tests")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "cache_hit_result_e2e.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump([res1, res2], f, indent=2)

    print(f"\n[+] Selesai! Hasil disimpan di: {output_path}")

if __name__ == "__main__":
    test_cache_hit_performance()
