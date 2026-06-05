import os
import sys

# Sesuaikan path agar bisa meng-import modul-modul dari parent directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from sqlalchemy import create_engine
from dotenv import load_dotenv

from reasoning.reasoning_service import ReasoningService

class DummyMinio:
    """Fallback in case Minio is not in app.state globally, we init it here"""
    def __init__(self):
        from minio import Minio
        self.client = Minio(
            os.getenv("MINIO_ENDPOINT"),
            access_key=os.getenv("MINIO_ACCESS_KEY"),
            secret_key=os.getenv("MINIO_SECRET_KEY"),
            secure=False
        )
    def get_object(self, *args, **kwargs):
        return self.client.get_object(*args, **kwargs)

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
    minio_client = DummyMinio()
    bucket_name = os.getenv("RAW_BUCKET_NAME", "raw")
    
    # file_id diambil dari parameter pytest fixture
    
    print(f"\n=== INITIALIZING SERVICE UNTUK FILE_ID: {file_id} ===")
    service = ReasoningService(engine, minio_client, bucket_name)
    
    # 1. Cek jumlah data MANUAL_REVIEW di tabel institution (Dibatasi 1 baris)
    print(f"\n[1] Mengambil baris MANUAL_REVIEW dari tabel institution (LIMIT 1)...")
    import time
    t0 = time.perf_counter()
    institution_rows = service.get_manual_review_rows(file_id, limit=1)
    t1 = time.perf_counter()
    
    assert institution_rows is not None, "Rows tidak boleh None"
    
    import pytest
    if len(institution_rows) == 0:
        pytest.skip("Tidak ada data MANUAL_REVIEW untuk testing")
    print(f"[+] Ditemukan {len(institution_rows)} baris MANUAL_REVIEW dalam {round(t1-t0, 2)} detik.")
    
    # 2. Build Comparison Pairs (Load Parquet + Master + Join)
    print(f"\n[2] Menjalankan proses load Parquet (MinIO), load Master (StarRocks), dan JOIN (DuckDB)...")
    t2 = time.perf_counter()
    joined_df, err = service.build_comparison_pairs(file_id, limit=1)
    t3 = time.perf_counter()
    
    assert err is None, f"Error saat menggabungkan data: {err}"
    assert joined_df.height > 0, "Hasil join tidak boleh kosong"
    print(f"[+] Berhasil menggabungkan {joined_df.height} baris data dalam {round(t3-t2, 2)} detik!")
    
    output_text = f"=== SQL LOGIC TEST: FILE {file_id} ===\n"
    output_text += f"Time to fetch institution rows: {round(t1-t0, 2)}s\n"
    output_text += f"Time to fetch Parquet + Master + Join: {round(t3-t2, 2)}s\n"
    output_text += f"Total Joined Rows: {joined_df.height}\n\n"
    
    # 3. Menampilkan sampel 1 baris pertama untuk stdout log
    print(f"\n[3] Menampilkan 1 baris pertama dari hasil join data:")
    for idx, row in enumerate(joined_df.iter_rows(named=True)):
        if idx >= 1:
            break
            
        print(f"\n--- Sampel ke-{idx+1} (ID Institution: {row['id']}) ---")
        assert row['nama_lengkap'] is not None, "Data Parquet tidak boleh full kosong"
        assert row['master_nama_lengkap'] is not None, "Data Master tidak boleh full kosong"
        
        output_text += f"--- Sampel ke-{idx+1} (ID Institution: {row['id']}) ---\n"
        output_text += ">> Data Incoming (Dari Parquet):\n"
        output_text += f"   Nama Lengkap   : {row['nama_lengkap']}\n"
        output_text += f"   Tempat Lahir   : {row['tempat_lahir']}\n"
        output_text += f"   Tanggal Lahir  : {service._format_date(row['tanggal_lahir'])}\n"
        output_text += f"   Jenis Kelamin  : {row['jenis_kelamin']}\n"
        output_text += f"   Nama Ibu       : {row['nama_ibu']}\n\n"
        output_text += ">> Data Master (Dari StarRocks):\n"
        output_text += f"   Nama Lengkap   : {row['master_nama_lengkap']}\n"
        output_text += f"   Tempat Lahir   : {row['master_tempat_lahir']}\n"
        output_text += f"   Tanggal Lahir  : {service._format_date(row['master_tanggal_lahir'])}\n"
        output_text += f"   Jenis Kelamin  : {row['master_jenis_kelamin']}\n"
        output_text += f"   Nama Ibu       : {row['master_nama_ibu']}\n\n"
        
    # Simpan hasil ke output_tests
    output_dir = os.path.join(os.path.dirname(__file__), "output_tests")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"sql_logic_result_{file_id}.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_text)
    print(f"Hasil sampel join disimpan di: {output_path}")

    print("\n[+] Test SQL dan Data Join selesai tanpa memanggil LLM.")
