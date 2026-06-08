"""Test skenario: Mengecek manual_matches dan men-trigger Celery worker untuk semua PENDING."""
import os
import sys
import pytest
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from reasoning.tasks import process_row_reasoning

def test_trigger_all_pending_workers():
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

    with engine.connect() as conn:
        print("\n[CHECK] Mengecek tabel manual_matches untuk data berstatus PENDING...")
        
        rows = conn.execute(text("""
            SELECT id
            FROM manual_matches 
            WHERE reasoning_status = 'PENDING'
        """)).mappings().all()

    if not rows:
        pytest.skip("Tidak ada data PENDING di manual_matches. Sistem idle.")

    print(f"[START] Ditemukan {len(rows)} data PENDING di manual_matches. Mengirim ke antrean Celery per baris...")

    queued_count = 0
    for row in rows:
        mm_id = row['id']
        
        # Trigger celery task secara asynchronous (.delay)
        task = process_row_reasoning.delay(mm_id)
        assert task.id is not None, f"Gagal mendapatkan task_id dari celery untuk id {mm_id}"
        
        print(f"   [QUEUED] id: {mm_id:<8} | Task ID: {task.id}")
        queued_count += 1
            
    print(f"\n[DONE] Selesai! {queued_count} tasks telah berhasil di-queue ke Celery Worker.")
    assert queued_count == len(rows), "Semua id yang ditemukan harus berhasil di-queue"
