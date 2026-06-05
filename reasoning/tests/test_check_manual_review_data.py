"""Diagnostic script to check MANUAL_REVIEW data availability."""
import os
import sys

# Sesuaikan path agar bisa meng-import modul-modul dari parent directory
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
        # 1. Cek berapa MANUAL_REVIEW rows untuk file_id ini
        count = conn.execute(text("""
            SELECT COUNT(*) as cnt FROM institution 
            WHERE match_result = 2 AND file_id = :file_id
        """), {"file_id": file_id}).mappings().first()
        
        import pytest
        if count['cnt'] == 0:
            pytest.skip("Tidak ada data MANUAL_REVIEW di database, skip test")

        # 2. Ambil 1 sample MANUAL_REVIEW
        sample = conn.execute(text("""
            SELECT id, id_incoming, nik_master, file_id, match_score, match_result
            FROM institution
            WHERE match_result = 2 AND file_id = :file_id
            LIMIT 1
        """), {"file_id": file_id}).mappings().first()

        assert sample is not None, "Gagal mengambil sample MANUAL_REVIEW"
        print(f"Sample MANUAL_REVIEW row:\n{dict(sample)}")

        # 3. Cek data file_id di uploaded_files
        # 3. Cek data file_id di uploaded_files
        file_record = conn.execute(text("""
            SELECT * FROM uploaded_files WHERE file_id = :file_id
        """), {"file_id": file_id}).mappings().first()

        assert file_record is not None, f"Data file_id {file_id} tidak ditemukan di uploaded_files"
        print(f"\nUploaded file record for {file_id}:\n{dict(file_record)}")
        
        # 4. Pastikan file Parquet ada di bucket
        minio_path = file_record['minio_path']
        assert minio_path is not None, "Minio path tidak boleh kosong"
        print(f"\nMinio path: {minio_path}")
        
        # Simpan hasil ke output_tests
        output_text = f"=== CHECK MANUAL REVIEW DATA ===\n"
        output_text += f"Total MANUAL_REVIEW rows: {count['cnt']}\n\n"
        output_text += f"Sample MANUAL_REVIEW row:\n{dict(sample)}\n\n"
        output_text += f"Uploaded file record for {file_id}:\n{dict(file_record)}\n\n"
        output_text += f"Minio path: {minio_path}\n"
        
        output_dir = os.path.join(os.path.dirname(__file__), "output_tests")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "check_manual_result.txt")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output_text)
        print(f"\nHasil pengecekan disimpan di: {output_path}")
