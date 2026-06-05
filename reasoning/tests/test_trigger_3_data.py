import os
import sys
import json
import time
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from reasoning.reasoning_service import ReasoningService

def run():
    load_dotenv()
    engine = create_engine(
        f"mysql+pymysql://"
        f"{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}@"
        f"{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/"
        f"{os.getenv('STARROCKS_DATABASE')}"
    )

    print("=== MENCARI DATA PENDING ===")
    
    with engine.connect() as conn:
        # Cari file_id yang punya status PENDING dan bisa di-join ke master (Grade A/B/C/D)
        # Coba grade A/B dulu
        res = conn.execute(text("""
            SELECT mm.file_id 
            FROM manual_matches mm
            JOIN master m ON mm.nik_incoming = m.nik
            WHERE mm.reasoning_status = 'PENDING'
            LIMIT 1
        """)).mappings().first()
        
        if not res:
            # Coba grade C/D
            res = conn.execute(text("""
                SELECT mm.file_id 
                FROM manual_matches mm
                JOIN institution inst ON inst.file_id = mm.file_id AND inst.id_incoming = mm.id_incoming
                JOIN master m ON inst.nik_master = m.nik
                WHERE mm.reasoning_status = 'PENDING' AND (mm.nik_incoming IS NULL OR mm.nik_incoming = '')
                LIMIT 1
            """)).mappings().first()

        if not res:
            print("Tidak ada data dengan reasoning_status='PENDING' yang siap di-join di manual_matches!")
            return
        
        file_id = res['file_id']
        count = conn.execute(text("SELECT COUNT(*) as c FROM manual_matches WHERE file_id = :fid AND reasoning_status = 'PENDING'"), {"fid": file_id}).mappings().first()['c']
        print(f"Ditemukan file_id: {file_id} dengan {count} baris PENDING.\n")
        
    print("=== TRIGGERING REASONING SYSTEM (LIMIT 3) ===")
    service = ReasoningService(engine)
    
    t0 = time.perf_counter()
    # Panggil langsung proses reasoning dengan melimit ke 3 data
    result = service.process_reasoning(file_id, dry_run=False, limit=3)
    elapsed = time.perf_counter() - t0
    
    print(f"\n=== SELESAI DALAM {round(elapsed, 2)}s ===")
    if result.get("status") == "error":
        print(f"Error Message: {result.get('message')}")
        return
        
    print(f"Processed : {result.get('processed_count')} baris")
    print(f"Updated   : {result.get('updated_count')} baris")
    
    # Simpan output hasil dari Python dictionary ke JSON
    out_dir = os.path.join(os.path.dirname(__file__), "output_tests")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, f"trigger_3_data_{file_id}.json")
    
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        
    print(f"\nHasil output lengkap (JSON) disimpan di: {out_file}\n")
    
    # Cek langsung ke database untuk verifikasi
    print("=== VERIFIKASI LANGSUNG KE DATABASE ===")
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, nama_incoming, reason, pattern_name, reasoning_source, reasoning_status 
            FROM manual_matches 
            WHERE file_id = :fid AND reasoning_status = 'COMPLETED'
            ORDER BY id DESC LIMIT 3
        """), {"fid": file_id}).mappings().all()
        
        if not rows:
            print("Belum ada data COMPLETED untuk file ini.")
        else:
            for r in rows:
                print(f"- ID: {r['id']}")
                print(f"  Nama Incoming  : {r['nama_incoming']}")
                reason_str = str(r['reason'])
                print(f"  Reason         : {reason_str[:100]}..." if r['reason'] else "  Reason         : None")
                print(f"  Pattern Name   : {r['pattern_name']}")
                print(f"  Source         : {r['reasoning_source']}")
                print(f"  Status         : {r['reasoning_status']}\n")

if __name__ == "__main__":
    run()
