import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
engine = create_engine(
    f"mysql+pymysql://"
    f"{os.getenv('STARROCKS_USER')}:"
    f"{os.getenv('STARROCKS_PASSWORD')}@"
    f"{os.getenv('STARROCKS_HOST')}:"
    f"{os.getenv('STARROCKS_PORT')}/"
    f"{os.getenv('STARROCKS_DATABASE')}"
)

file_id = "558f1a53"

with engine.begin() as conn:
    # Reset data agar dianggap "belum diproses" oleh reasoning
    res = conn.execute(
        text("""
        UPDATE institution 
        SET reason = NULL, pattern_name = NULL, reasoning_source = NULL 
        WHERE file_id = :file_id AND match_result = 2
        """), 
        {"file_id": file_id}
    )
    print(f"Berhasil mereset data untuk file_id '{file_id}'.")
    print("Silakan jalankan ulang pytest, test tidak akan di-skip lagi!")
