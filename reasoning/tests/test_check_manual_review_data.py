"""Diagnostic script to check MANUAL_REVIEW data availability via native SQL join."""
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

    with engine.connect() as conn:
        # 1. Cek berapa MANUAL_REVIEW rows untuk file_id ini di institution
        count = conn.execute(text("""
            SELECT COUNT(*) as cnt FROM institution 
            WHERE match_result = 2 AND file_id = :file_id
        """), {"file_id": file_id}).mappings().first()

        import pytest
        if count['cnt'] == 0:
            pytest.skip("Tidak ada data MANUAL_REVIEW di institution, skip test")

        # 2. Cek apakah data di manual_matches tersedia untuk file ini
        mm_count = conn.execute(text("""
            SELECT COUNT(*) as cnt FROM manual_matches WHERE file_id = :file_id
        """), {"file_id": file_id}).mappings().first()

        print(f"\n=== CHECK MANUAL REVIEW DATA ===")
        print(f"Total MANUAL_REVIEW rows (institution): {count['cnt']}")
        print(f"Total rows in manual_matches: {mm_count['cnt']}")

        if mm_count['cnt'] == 0:
            pytest.skip(f"Belum ada data di tabel manual_matches untuk file_id {file_id}")

        # 3. Ambil 1 sample JOIN antara institution + manual_matches + master
        sample = conn.execute(text("""
            SELECT 
                inst.id,
                inst.id_incoming,
                inst.nik_master,
                mm.nama_incoming,
                mm.tempat_lahir_incoming,
                mm.tanggal_lahir_incoming,
                mm.jenis_kelamin_incoming,
                mm.nama_ibu_incoming
            FROM institution inst
            JOIN manual_matches mm ON inst.file_id = mm.file_id AND inst.id_incoming = mm.id_incoming
            WHERE inst.match_result = 2 AND inst.file_id = :file_id
            LIMIT 1
        """), {"file_id": file_id}).mappings().first()

        assert sample is not None, "Gagal mengambil sample MANUAL_REVIEW via JOIN"
        print(f"\nSample JOIN result:\n{dict(sample)}")

        # Simpan hasil ke output_tests
        output_text = f"=== CHECK MANUAL REVIEW DATA ===\n"
        output_text += f"Total MANUAL_REVIEW rows (institution): {count['cnt']}\n"
        output_text += f"Total rows in manual_matches: {mm_count['cnt']}\n\n"
        output_text += f"Sample JOIN result:\n{dict(sample)}\n"

        output_dir = os.path.join(os.path.dirname(__file__), "output_tests")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "check_manual_result.txt")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output_text)
        print(f"\nHasil pengecekan disimpan di: {output_path}")
