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

# === STEP 1: DROP kolom lama dari tabel lain (bersihkan) ===
drop_ddls = [
    # Hapus dari institution — tidak akan ditulis lagi oleh Reasoning
    "ALTER TABLE institution DROP COLUMN reason;",
    "ALTER TABLE institution DROP COLUMN pattern_name;",
    "ALTER TABLE institution DROP COLUMN reasoning_source;",
    # Hapus dari uploaded_files — tracking status sudah pindah ke manual_matches
    "ALTER TABLE uploaded_files DROP COLUMN reasoning_status;",
]

# === STEP 2: ADD kolom baru ke manual_matches (target tulis reasoning) ===
add_ddls = [
    "ALTER TABLE manual_matches ADD COLUMN reason VARCHAR(65533) COMMENT 'Hasil reasoning AI dalam Bahasa Indonesia';",
    "ALTER TABLE manual_matches ADD COLUMN pattern_name VARCHAR(255) COMMENT 'Kode pola, misal: P001_NAMA_BEDA__TGLLAHIR_KOSONG';",
    "ALTER TABLE manual_matches ADD COLUMN reasoning_source VARCHAR(20) COMMENT 'LLM atau CACHE';",
    """ALTER TABLE manual_matches ADD COLUMN reasoning_status VARCHAR(30) NOT NULL DEFAULT 'PENDING' 
    COMMENT 'Status proses AI: PENDING | PROCESSING | COMPLETED | SKIPPED | FAILED';""",
]

# === STEP 3: Tabel reasoning_patterns — tetap ada, tidak diubah ===
create_ddls = [
    """
    CREATE TABLE IF NOT EXISTS reasoning_patterns (
        pattern_hash      VARCHAR(64)    COMMENT 'SHA256 hash dari pattern signature',
        pattern_name      VARCHAR(255)   COMMENT 'Nama pola yang mudah dibaca manusia, misal: P001_NAMA_BEDA',
        pattern_signature VARCHAR(500)   COMMENT 'String lengkap deskripsi pola',
        reason_template   VARCHAR(1000)  COMMENT 'Template reason dari LLM dengan placeholder',
        sample_id         BIGINT         COMMENT 'ID manual_matches pertama yang menggunakan pola ini',
        hit_count         INT DEFAULT '1' COMMENT 'Jumlah baris yang cocok dengan pola ini',
        created_at        DATETIME       COMMENT 'Waktu pola pertama kali ditemukan',
        updated_at        DATETIME       COMMENT 'Waktu terakhir hit_count diupdate'
    ) ENGINE = OLAP
    PRIMARY KEY(pattern_hash)
    DISTRIBUTED BY HASH(pattern_hash) BUCKETS 1
    PROPERTIES("replication_num" = "1");
    """
]

def run_ddls(label, ddl_list):
    print(f"\n{'='*50}")
    print(f" {label}")
    print('='*50)
    with e.begin() as conn:
        for sql in ddl_list:
            sql_preview = sql.strip()[:70].replace('\n', ' ')
            try:
                conn.execute(text(sql))
                print(f"  [OK]  SUCCESS : {sql_preview}...")
            except Exception as ex:
                err = str(ex)
                if any(k in err for k in ["Duplicate column name", "already exists", "Unknown column"]):
                    print(f"  [SKIP] SKIP    : {sql_preview}... ({err[:60]})")
                else:
                    print(f"  [ERR] FAILED  : {sql_preview}... Error: {err[:80]}")

run_ddls("STEP 1: DROP kolom lama (institution + uploaded_files)", drop_ddls)
run_ddls("STEP 2: ADD kolom baru ke manual_matches", add_ddls)
run_ddls("STEP 3: CREATE reasoning_patterns (if not exists)", create_ddls)

print("\n\n=== Verifikasi Schema Akhir ===")
with e.connect() as conn:
    print("\n[manual_matches columns]:")
    res = conn.execute(text("DESCRIBE manual_matches")).fetchall()
    for r in res:
        print(f"  {r[0]:35s} {r[1]}")
    
    print("\n[institution columns — pastikan kolom lama sudah hilang]:")
    res = conn.execute(text("DESCRIBE institution")).fetchall()
    for r in res:
        print(f"  {r[0]:35s} {r[1]}")

print("\n[OK] Migration completed.")
