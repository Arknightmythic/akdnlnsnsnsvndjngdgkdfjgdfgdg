import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(
    f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}"
    f"@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}"
)

with engine.connect() as conn:
    print("=== CHECK ===")
    res = conn.execute(text("SELECT COUNT(*) FROM manual_matches")).fetchall()
    print("manual_matches count:", res[0][0])
    
    res = conn.execute(text("SELECT COUNT(*) FROM institution WHERE match_result = 2")).fetchall()
    print("institution match_result=2 count:", res[0][0])
    
    res = conn.execute(text("""
        SELECT COUNT(*)
        FROM institution inst
        JOIN manual_matches mm ON inst.file_id = mm.file_id
        WHERE inst.match_result = 2 
    """)).fetchall()
    print("JOIN with file_id count:", res[0][0])
    
    res = conn.execute(text("""
        SELECT COUNT(*)
        FROM institution inst
        JOIN manual_matches mm ON inst.file_id = mm.file_id AND inst.id_incoming = mm.id_incoming
        WHERE inst.match_result = 2 
    """)).fetchall()
    print("JOIN with file_id AND id_incoming count:", res[0][0])
