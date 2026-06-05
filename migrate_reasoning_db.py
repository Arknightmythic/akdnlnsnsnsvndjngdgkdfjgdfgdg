import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
e = create_engine(
    f"mysql+pymysql://"
    f"{os.getenv('STARROCKS_USER')}:"
    f"{os.getenv('STARROCKS_PASSWORD')}@"
    f"{os.getenv('STARROCKS_HOST')}:"
    f"{os.getenv('STARROCKS_PORT')}/"
    f"{os.getenv('STARROCKS_DATABASE')}"
)

ddls = [
    # institution table updates (ignore errors if columns exist)
    "ALTER TABLE institution ADD COLUMN reason VARCHAR(65533);",
    "ALTER TABLE institution ADD COLUMN pattern_name VARCHAR(255);",
    "ALTER TABLE institution ADD COLUMN reasoning_source VARCHAR(20) COMMENT 'LLM atau CACHE';",
    
    # uploaded_files table updates
    "ALTER TABLE uploaded_files ADD COLUMN reasoning_status VARCHAR(30) DEFAULT 'PENDING' COMMENT 'Status proses reasoning: PENDING | PROCESSING | COMPLETED | SKIPPED';",
    
    # reasoning_patterns table creation
    """
    CREATE TABLE IF NOT EXISTS reasoning_patterns (
        pattern_hash      VARCHAR(64)    COMMENT 'SHA256 hash dari pattern signature',
        pattern_name      VARCHAR(255)   COMMENT 'Nama pola yang mudah dibaca manusia, misal: P001_NAMA_BEDA',
        pattern_signature VARCHAR(500)   COMMENT 'String lengkap deskripsi pola, misal: nama_lengkap:BEDA|tempat_lahir:SAMA|...',
        reason_template   VARCHAR(1000)  COMMENT 'Template reason dari LLM dengan placeholder',
        sample_id         BIGINT         COMMENT 'ID institution pertama yang menggunakan pola ini (untuk tracing)',
        hit_count         INT DEFAULT '1' COMMENT 'Jumlah baris yang cocok dengan pola ini',
        created_at        DATETIME       COMMENT 'Waktu pola pertama kali ditemukan',
        updated_at        DATETIME       COMMENT 'Waktu terakhir hit_count diupdate'
    ) ENGINE = OLAP
    PRIMARY KEY(pattern_hash)
    DISTRIBUTED BY HASH(pattern_hash) BUCKETS 1
    PROPERTIES("replication_num" = "1");
    """
]

with e.begin() as conn:
    for sql in ddls:
        try:
            conn.execute(text(sql))
            print(f"SUCCESS: {sql[:50]}...")
        except Exception as ex:
            if "Duplicate column name" in str(ex) or "Table" in str(ex) and "already exists" in str(ex):
                print(f"ALREADY EXISTS: {sql[:50]}...")
            else:
                print(f"FAILED: {sql[:50]}... Error: {str(ex)}")

print("Database schema migration completed.")
