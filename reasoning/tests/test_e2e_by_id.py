"""End-to-End Test for a single ID to measure separate fetching and reasoning times."""
import os
import sys
import time
import json
import argparse
import polars as pl
import duckdb

# Sesuaikan path agar bisa meng-import modul-modul dari parent directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

from reasoning.reasoning_service import ReasoningService

class DummyMinio:
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
    minio_client = DummyMinio()
    bucket_name = os.getenv("RAW_BUCKET_NAME", "raw")
    
    print(f"=== INITIALIZING SERVICE UNTUK INSTITUTION ID: {institution_id} ===")
    service = ReasoningService(engine, minio_client, bucket_name)
    
    timings = {}
    
    # 1. SQL Get Institution Row
    t0 = time.perf_counter()
    with engine.connect() as conn:
        # Kita cek file_id nya dulu
        raw_row = conn.execute(text("SELECT file_id FROM institution WHERE id = :id"), {"id": institution_id}).mappings().first()
        if not raw_row:
            print(f"[-] Data dengan ID {institution_id} tidak ditemukan.")
            return
            
        file_id = raw_row["file_id"]
        
        # Gunakan query yang 100% sama dengan reasoning_service
        query_str = """
            SELECT 
                id,
                id_incoming,
                nik_master
            FROM institution
            WHERE id = :id
        """
        inst_row = conn.execute(text(query_str), {"id": institution_id}).mappings().first()
        
    timings["sql_get_institution_s"] = round(time.perf_counter() - t0, 2)
    
    if not inst_row:
        print(f"[-] Data dengan ID {institution_id} tidak dapat difetch ulang.")
        return
        
    print(f"[+] Ditemukan file_id = {file_id}. Mengambil data file...")
    
    # 2. Get MinIO path
    uploaded_file = service.matching_service.get_uploaded_file(file_id)
    if not uploaded_file:
        print("[-] Data uploaded_files tidak ditemukan.")
        return
        
    # 3. Load Parquet
    print(f"[+] Loading Parquet dari MinIO...")
    t0 = time.perf_counter()
    incoming_df = service.matching_service.load_parquet_from_minio(uploaded_file["minio_path"])
    timings["load_parquet_minio_s"] = round(time.perf_counter() - t0, 2)
    
    # 4. Load Master
    print(f"[+] Loading tabel Master dari StarRocks...")
    t0 = time.perf_counter()
    master_df = service.matching_service.fetch_master_dataset()
    timings["sql_load_master_s"] = round(time.perf_counter() - t0, 2)
    
    # 5. DuckDB Join
    print(f"[+] Menjalankan DuckDB Join...")
    t0 = time.perf_counter()
    grade = str(uploaded_file.get("grade") or "").strip().upper()
    incoming_join_col = "id" if grade in ["C", "D"] else ("id" if "gradeD" in uploaded_file["minio_path"] else "nik")
    
    inst_df = pl.DataFrame([dict(inst_row)])
    con = duckdb.connect()
    con.register("incoming_df", incoming_df.to_arrow())
    con.register("master_df", master_df.to_arrow())
    con.register("inst_df", inst_df.to_arrow())
    
    joined_df = con.execute(f"""
        SELECT 
            inst.id,
            i.nama_clean AS nama_lengkap,
            i.tempat_lahir_clean AS tempat_lahir,
            i.tanggal_lahir_clean AS tanggal_lahir,
            i.jenis_kelamin_clean AS jenis_kelamin,
            i.nama_ibu_clean AS nama_ibu,
            m.nama_master_clean AS master_nama_lengkap,
            m.tempat_lahir_master_clean AS master_tempat_lahir,
            m.tanggal_lahir_master_clean AS master_tanggal_lahir,
            m.jenis_kelamin_master_clean AS master_jenis_kelamin,
            m.nama_ibu_master_clean AS master_nama_ibu
        FROM inst_df inst
        JOIN incoming_df i ON inst.id_incoming = i.{incoming_join_col}
        JOIN master_df m ON inst.nik_master = m.nik
    """).pl()
    timings["duckdb_join_s"] = round(time.perf_counter() - t0, 2)
    
    if joined_df.height == 0:
        print("[-] Join gagal atau kosong.")
        return
        
    row = joined_df.row(0, named=True)
    
    # 6. LLM Reasoning
    print(f"[+] Mengirim data ke Ollama AI untuk Reasoning...")
    t0 = time.perf_counter()
    
    def _fmt(val):
        v = str(val).strip()
        if v.lower() in ["none", "null", "nan", ""]:
            return "KOSONG"
        return v

    human_prompt = f"ID: {row['id']}\n\nInstitution (Incoming):\n"
    human_prompt += f"  Nama Lengkap   : {_fmt(row['nama_lengkap'])}\n"
    human_prompt += f"  Tempat Lahir   : {_fmt(row['tempat_lahir'])}\n"
    human_prompt += f"  Tanggal Lahir  : {_fmt(service._format_date(row['tanggal_lahir']))}\n"
    human_prompt += f"  Jenis Kelamin  : {_fmt(row['jenis_kelamin'])}\n"
    human_prompt += f"  Nama Ibu       : {_fmt(row['nama_ibu'])}\n\n"
    human_prompt += f"Master:\n"
    human_prompt += f"  Nama Lengkap   : {_fmt(row['master_nama_lengkap'])}\n"
    human_prompt += f"  Tempat Lahir   : {_fmt(row['master_tempat_lahir'])}\n"
    human_prompt += f"  Tanggal Lahir  : {_fmt(service._format_date(row['master_tanggal_lahir']))}\n"
    human_prompt += f"  Jenis Kelamin  : {_fmt(row['master_jenis_kelamin'])}\n"
    human_prompt += f"  Nama Ibu       : {_fmt(row['master_nama_ibu'])}\n"

    messages = [
        SystemMessage(content=service.system_prompt.strip()),
        HumanMessage(content=human_prompt.strip())
    ]
    
    response = service.llm.invoke(messages)
    timings["llm_reasoning_s"] = round(time.perf_counter() - t0, 2)
    
    reason = response.reason
        
    # === SIMPAN HASIL ===
    output_dir = os.path.join(os.path.dirname(__file__), "output_tests")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"e2e_result_{institution_id}.json")
    
    final_output = {
        "institution_id": institution_id,
        "file_id": file_id,
        "reason": reason,
        "timings_seconds": timings,
        "raw_data": {
            "incoming": {
                "nama_lengkap": row['nama_lengkap'],
                "tempat_lahir": row['tempat_lahir'],
                "tanggal_lahir": service._format_date(row['tanggal_lahir']),
                "nama_ibu": row['nama_ibu']
            },
            "master": {
                "nama_lengkap": row['master_nama_lengkap'],
                "tempat_lahir": row['master_tempat_lahir'],
                "tanggal_lahir": service._format_date(row['master_tanggal_lahir']),
                "nama_ibu": row['master_nama_ibu']
            }
        }
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2)
        
    print(f"\n[+] Selesai! Hasil E2E disimpan di: {output_path}")
    print(json.dumps(final_output, indent=2))
