"""Diagnostic: cek ketersediaan data di manual_matches untuk reasoning."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

def test_check_manual_review_data(file_id):
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
    import pytest

    with engine.connect() as conn:
        # 1. Cek berapa baris di manual_matches untuk file_id ini
        total = conn.execute(text("""
            SELECT COUNT(*) as cnt FROM manual_matches WHERE file_id = :fid
        """), {"fid": file_id}).mappings().first()

        if total["cnt"] == 0:
            pytest.skip(f"Tidak ada data di manual_matches untuk file_id={file_id}")

        # 2. Cek yang masih belum diproses
        pending = conn.execute(text("""
            SELECT COUNT(*) as cnt FROM manual_matches
            WHERE file_id = :fid AND reasoning_status IN ('PENDING', 'FAILED')
        """), {"fid": file_id}).mappings().first()

        print(f"\n=== CHECK manual_matches untuk file_id: {file_id} ===")
        print(f"Total rows         : {total['cnt']}")
        print(f"Belum diproses     : {pending['cnt']}")

        # 3. Ambil 1 sample
        sample = conn.execute(text("""
            SELECT id, id_incoming, nik_incoming,
                   nama_incoming, tempat_lahir_incoming, tanggal_lahir_incoming,
                   jenis_kelamin_incoming, nama_ibu_incoming,
                   reasoning_status, reasoning_source
            FROM manual_matches
            WHERE file_id = :fid
            LIMIT 1
        """), {"fid": file_id}).mappings().first()

        assert sample is not None
        print(f"\nSample row:\n{dict(sample)}")

        # Simpan ke output
        output_dir = os.path.join(os.path.dirname(__file__), "output_tests")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "check_manual_result.txt")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"file_id       : {file_id}\n")
            f.write(f"Total rows    : {total['cnt']}\n")
            f.write(f"Belum diproses: {pending['cnt']}\n\n")
            f.write(f"Sample:\n{dict(sample)}\n")
        print(f"\nHasil disimpan di: {output_path}")
