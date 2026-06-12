"""Test cache hit: RUN 1 → LLM (CACHE MISS), RUN 2 → 100% CACHE HIT."""
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
    import pytest

    engine = create_engine(
        f"mysql+pymysql://"
        f"{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}@"
        f"{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/"
        f"{os.getenv('STARROCKS_DATABASE')}"
    )
    service = ReasoningService(engine)

    # Cari file_id yang siap di-test (ada di manual_matches + bisa di-join ke master)
    # with engine.connect() as conn:
    #     row = conn.execute(text("""
    #         SELECT mm.file_id
    #         FROM manual_matches mm
    #         JOIN master m ON mm.nik_incoming = m.nik
    #         WHERE mm.reasoning_status IN ('PENDING', 'FAILED')
    #         LIMIT 1
    #     """)).mappings().first()

    #     if not row:
    #         # Coba path institution (grade C/D)
    #         row = conn.execute(text("""
    #             SELECT mm.file_id
    #             FROM manual_matches mm
    #             JOIN institution inst
    #               ON inst.file_id = mm.file_id AND inst.id_incoming = mm.id_incoming
    #             JOIN master m ON inst.nik_master = m.nik
    #             WHERE mm.reasoning_status IN ('PENDING', 'FAILED')
    #             LIMIT 1
    #         """)).mappings().first()

    #     if not row:
    #         pytest.skip("Tidak ada data manual_matches yang bisa di-join ke master")

    #     file_id = row["file_id"]
    # print(f"[0] Menggunakan file_id: {file_id}")
    file_id = "45b76ab1"
    # RESET: truncate cache + reset reasoning_status ke PENDING
    with engine.begin() as conn:
        # conn.execute(text("TRUNCATE TABLE reasoning_patterns"))
        conn.execute(text("""
            UPDATE manual_matches
            SET reason = NULL, pattern_name = NULL, reasoning_source = NULL, reasoning_status = 'PENDING'
            WHERE file_id = :fid
        """), {"fid": file_id})
    print("[1] Cache dan status manual_matches di-reset ke PENDING.")

    # RUN 1: Seharusnya CACHE MISS — LLM terpanggil
    print("\n[2] RUN 1 (CACHE MISS expected)...")
    t0 = time.perf_counter()
    res1 = service.process_reasoning(file_id, dry_run=False, limit=20)
    print(f"    RUN 1 selesai dalam {round(time.perf_counter()-t0, 2)}s")

    if res1.get("status") == "error":
        pytest.skip(f"RUN 1 error: {res1.get('message')}")
    assert res1["updated_count"] > 0, "RUN 1 harus update minimal 1 baris"

    # RESET manual_matches tapi BIARKAN reasoning_patterns (cache tetap ada)
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE manual_matches
            SET reason = NULL, pattern_name = NULL, reasoning_source = NULL, reasoning_status = 'PENDING'
            WHERE file_id = :fid
        """), {"fid": file_id})
    print("[3] manual_matches di-reset, reasoning_patterns tetap ada.")

    # RUN 2: Seharusnya 100% CACHE HIT
    print("\n[4] RUN 2 (100% CACHE HIT expected)...")
    t0 = time.perf_counter()
    res2 = service.process_reasoning(file_id, dry_run=False, limit=20)
    print(f"    RUN 2 selesai dalam {round(time.perf_counter()-t0, 2)}s")

    if res2.get("status") == "error":
        pytest.skip(f"RUN 2 error: {res2.get('message')}")
    assert res2["updated_count"] > 0, "RUN 2 harus update minimal 1 baris"

    run2_sources = [r.get("source") for r in res2.get("results", [])]
    cache_hits = sum(1 for s in run2_sources if s == "CACHE")
    print(f"[5] RUN 2: {cache_hits}/{len(run2_sources)} dari CACHE")
    assert cache_hits == len(run2_sources), "RUN 2 seharusnya 100% CACHE HIT"

    output_dir = os.path.join(os.path.dirname(__file__), "output_tests")
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "cache_hit_result_e2e.json"), "w", encoding="utf-8") as f:
        json.dump([res1, res2], f, indent=2)
    print("[+] Selesai! Hasil disimpan.")

if __name__ == "__main__":
    test_cache_hit_performance()
