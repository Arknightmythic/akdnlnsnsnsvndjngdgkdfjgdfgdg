import os
import sys
import json
from sqlalchemy import create_engine, text

# Tambahkan root directory ke sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from dotenv import load_dotenv
from reasoning.handler import ReasoningHandler

def test_manual_file_id():
    """
    Test langsung menembak SELURUH baris untuk 1 file_id di tabel manual_matches:
    file_id = '94080cfe'
    """
    load_dotenv()

    # Setup koneksi Database
    DATABASE_URL = (
        f"mysql+pymysql://"
        f"{os.getenv('STARROCKS_USER')}:"
        f"{os.getenv('STARROCKS_PASSWORD')}@"
        f"{os.getenv('STARROCKS_HOST')}:"
        f"{os.getenv('STARROCKS_PORT')}/"
        f"{os.getenv('STARROCKS_DATABASE')}"
    )
    engine = create_engine(DATABASE_URL)

    # Inisialisasi Handler
    handler = ReasoningHandler(engine)

    file_id = "94080cfe"

    print(f"\n[+] Mulai testing LLM Reasoning secara BATCH untuk file_id: {file_id}")
    
    try:
        # import time
        # # Paksa reset status di database agar bisa di-test berulang-ulang
        # with engine.begin() as conn:
        #     # 1. HAPUS SELURUH CACHE LAMA
        #     conn.execute(text("TRUNCATE TABLE reasoning_patterns;"))
        #     print("[+] Cache reasoning_patterns lama berhasil dihapus!")

        # print("[+] Menunggu 3 detik agar StarRocks selesai melakukan Truncate di semua node...")
        # time.sleep(3)

        with engine.begin() as conn:
            # 2. Reset status semua row untuk file_id ini menjadi PENDING
            conn.execute(
                text("""
                    UPDATE manual_matches 
                    SET reasoning_status = 'PENDING',
                        reason = NULL,
                        pattern_name = NULL,
                        reasoning_source = NULL
                    WHERE file_id = :file_id
                """),
                {"file_id": file_id}
            )
            print(f"[+] Status database di-reset menjadi PENDING untuk semua row di file_id: {file_id}.")

        # Eksekusi reasoning untuk keseluruhan file secara sinkron (TANPA WORKER)!
        result = handler.reasoning_service.process_reasoning(file_id, dry_run=False)

        print("\n[SUCCESS] AI Reasoning Selesai!\n")
        print("=== HASIL REASONING ===")
        print(json.dumps(result, indent=2))
        print("=======================")

    except Exception as e:
        print(f"\n[ERROR] Gagal menjalankan reasoning: {str(e)}")
        raise e

if __name__ == "__main__":
    test_manual_file_id()
