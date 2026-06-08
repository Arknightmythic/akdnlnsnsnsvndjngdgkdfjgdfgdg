import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

def run():
    load_dotenv()
    engine = create_engine(
        f"mysql+pymysql://"
        f"{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}@"
        f"{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/"
        f"{os.getenv('STARROCKS_DATABASE')}"
    )

    with engine.begin() as conn:
        print("1. Mengosongkan tabel reasoning_patterns (Cache)...")
        conn.execute(text("TRUNCATE TABLE reasoning_patterns"))
        
        print("2. Mereset SELURUH data reasoning di manual_matches ke PENDING...")
        conn.execute(text("""
            UPDATE manual_matches 
            SET reasoning_status = 'PENDING', 
                reason = NULL, 
                pattern_name = NULL, 
                reasoning_source = NULL
            WHERE reasoning_status != 'PENDING' OR reason IS NOT NULL
        """))
        
        # Verifikasi
        res = conn.execute(text("SELECT COUNT(*) as c FROM manual_matches WHERE reason IS NOT NULL")).mappings().first()
        print(f"3. Sisa data yang masih memiliki alasan (reason): {res['c']} baris")

    print("\nDatabase telah dibersihkan sepenuhnya dari cache sebelumnya!")

if __name__ == "__main__":
    run()
