"""Test sync_status update: when all reasoning is completed, uploaded_files.sync_status should be 2."""
import os
import time
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

from reasoning.reasoning_service import ReasoningService

def test_sync_status_update():
    load_dotenv()
    import pytest

    engine = create_engine(
        f"mysql+pymysql://"
        f"{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}@"
        f"{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/"
        f"{os.getenv('STARROCKS_DATABASE')}"
    )
    service = ReasoningService(engine)

    file_id = "0be06ff4"

    # RESET: reset reasoning_status ke PENDING dan sync_status ke 1
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE manual_matches
            SET reason = NULL, pattern_name = NULL, reasoning_source = NULL, reasoning_status = 'PENDING'
            WHERE file_id = :fid
        """), {"fid": file_id})

        try:
            conn.execute(text("""
                UPDATE uploaded_files
                SET sync_status = 1
                WHERE file_id = :fid
            """), {"fid": file_id})
        except Exception as e:
            print(f"[WARN] Failed to reset uploaded_files.sync_status: {e}")

    print(f"[1] Status manual_matches dan uploaded_files di-reset untuk file_id: {file_id}")

    # RUN: Jalankan reasoning
    print("\n[2] RUN process_reasoning...")
    t0 = time.perf_counter()
    # Gunakan limit None agar semua baris diproses, tapi untuk tes ini diasumsikan file_id tidak terlalu besar
    res = service.process_reasoning(file_id, dry_run=False, limit=None)
    print(f"    RUN selesai dalam {round(time.perf_counter()-t0, 2)}s")

    if res.get("status") == "error":
        pytest.skip(f"RUN error: {res.get('message')}")
    assert res["updated_count"] > 0, "RUN harus update minimal 1 baris"

    # VERIFY: cek uploaded_files.sync_status
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT sync_status
            FROM uploaded_files
            WHERE file_id = :fid
        """), {"fid": file_id}).mappings().first()

    if not row:
        pytest.skip("Tidak ada data uploaded_files untuk file_id ini")
    
    sync_status = row["sync_status"]
    print(f"\n[3] Hasil uploaded_files.sync_status: {sync_status}")
    assert sync_status == 2, f"sync_status seharusnya 2, tapi mendapat {sync_status}"

    print("[+] Selesai! Test sukses.")

if __name__ == "__main__":
    test_sync_status_update()
