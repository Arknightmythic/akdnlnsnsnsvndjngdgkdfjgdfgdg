import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(
    f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}"
    f"@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}"
)

query = text("""
    SELECT 
        inst.id as id,
        mm.nama_incoming AS nama_lengkap,
        mm.tempat_lahir_incoming AS tempat_lahir,
        mm.tanggal_lahir_incoming AS tanggal_lahir,
        mm.jenis_kelamin_incoming AS jenis_kelamin,
        mm.nama_ibu_incoming AS nama_ibu,
        m.nama_lengkap AS master_nama_lengkap,
        m.tempat_lahir AS master_tempat_lahir,
        m.tanggal_lahir AS master_tanggal_lahir,
        m.jenis_kelamin AS master_jenis_kelamin,
        m.nama_ibu AS master_nama_ibu
    FROM institution inst
    JOIN manual_matches mm ON inst.file_id = mm.file_id AND inst.id_incoming = mm.id_incoming
    JOIN master m ON inst.nik_master = m.nik
    WHERE inst.file_id = :file_id 
      AND inst.match_result = 2 
      AND inst.reasoning_source IS NULL
""")

with engine.connect() as conn:
    # Just try to see if query parses correctly (we need a valid file_id or just limit 1 without WHERE)
    res = conn.execute(text("""
    SELECT 
        inst.id as id,
        mm.nama_incoming AS nama_lengkap,
        mm.tempat_lahir_incoming AS tempat_lahir,
        mm.tanggal_lahir_incoming AS tanggal_lahir,
        mm.jenis_kelamin_incoming AS jenis_kelamin,
        mm.nama_ibu_incoming AS nama_ibu,
        m.nama_lengkap AS master_nama_lengkap,
        m.tempat_lahir AS master_tempat_lahir,
        m.tanggal_lahir AS master_tanggal_lahir,
        m.jenis_kelamin AS master_jenis_kelamin,
        m.nama_ibu AS master_nama_ibu
    FROM institution inst
    JOIN manual_matches mm ON inst.file_id = mm.file_id AND inst.id_incoming = mm.id_incoming
    JOIN master m ON inst.nik_master = m.nik
    LIMIT 1
    """)).fetchall()
    
    print(res)
