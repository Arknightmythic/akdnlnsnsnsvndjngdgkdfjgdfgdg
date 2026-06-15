import os
import sys
import json
from sqlalchemy import create_engine

from dotenv import load_dotenv
from reasoning.handler import ReasoningHandler

def test_manual_mm_id():
    """
    Test langsung menembak 1 baris spesifik di tabel manual_matches:
    mm_id = 234495
    file_id = '5621ca9b'
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

    mm_id = 234495
    file_id = "5621ca9b"

    print(f"\n[+] Mulai testing LLM Reasoning untuk mm_id: {mm_id} (file: {file_id})")
    
    try:
        from sqlalchemy import text
        # Paksa reset status di database agar bisa di-test berulang-ulang
        with engine.begin() as conn:
            # HAPUS SELURUH CACHE LAMA YANG BERBAHASA INDONESIA
            conn.execute(text("TRUNCATE TABLE reasoning_patterns;"))
            print("[+] Cache reasoning_patterns lama berhasil dihapus!")

            # Reset status row menjadi PENDING
            conn.execute(
                text("UPDATE manual_matches SET reasoning_status = 'PENDING' WHERE id = :mm_id"),
                {"mm_id": mm_id}
            )
            print("[+] Status database di-reset menjadi PENDING untuk mm_id ini.")

        # Eksekusi reasoning! (TIDAK PAKAI dry_run agar hasil Inggris-nya tersimpan di DB)
        result = handler.run_reasoning_by_id(mm_id)

        print("\n[SUCCESS] AI Reasoning Selesai!\n")
        print("=== HASIL REASONING (BAHASA INGGRIS) ===")
        print(json.dumps(result, indent=2))
        print("========================================")

        assert result["status"] == "success", "Reasoning gagal dijalankan"
        assert "reason" in result, "Output LLM tidak ditemukan!"

    except Exception as e:
        print(f"\n[ERROR] Gagal menjalankan reasoning: {str(e)}")
        raise e

if __name__ == "__main__":
    test_manual_mm_id()
