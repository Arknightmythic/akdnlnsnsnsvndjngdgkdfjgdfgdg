import polars as pl
from sqlalchemy import text

class StarrocksService:
    def __init__(self, engine):
        self.engine = engine
        self.sync_status_in_progress_query = text("""
            UPDATE uploaded_files
            SET
            sync_status = 1
            WHERE file_id = :file_id
        """)
        self.sync_status_query = text("""
            UPDATE uploaded_files
            SET
            is_sync = 1,
            sync_status = :sync_status
            WHERE file_id = :file_id
        """)
        self.manual_review_insert_query = text("""
            INSERT INTO manual_matches (file_id, id_incoming, nik_incoming, nama_incoming, 
                                        tempat_lahir_incoming, area_incoming, tanggal_lahir_incoming, nama_ibu_incoming)
            VALUES (:file_id, :id_incoming, :nik_incoming, :nama_incoming,
                    :tempat_lahir_incoming, :area_incoming, :tanggal_lahir_incoming, :nama_ibu_incoming)
        """)
        print("Starrocks Service Initialized!")

    def get_uploaded_file(self, file_id):
        query = text("""
            SELECT
                file_id,
                minio_path,
                upload_timestamp,
                grade
            FROM uploaded_files
            WHERE file_id = :file_id
        """)

        with self.engine.connect() as conn:
            result = conn.execute(query,{"file_id": file_id}).mappings().first()

        return result

    def fetch_master_dataset(self):

        query = text("""
            SELECT nik,nama_lengkap,tempat_lahir,provinsi,kabupaten,kecamatan,
            kelurahan,tanggal_lahir,jenis_kelamin,nama_ibu,status_kematian
            FROM master
        """)

        with self.engine.connect() as conn:
            rows = conn.execute(query).mappings().all()

        return (
            pl.DataFrame(rows)
            .with_columns([
                pl.col("nik")
                    .cast(pl.Utf8),
                pl.col("nama_lengkap")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("nama_master_clean"),
                pl.col("tempat_lahir")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("tempat_lahir_master_clean"),
                pl.col("provinsi")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("provinsi_master_clean"),
                pl.col("kabupaten")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("kabupaten_master_clean"),
                pl.col("kecamatan")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("kecamatan_master_clean"),
                pl.col("kelurahan")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("kelurahan_master_clean"),
                pl.col("tanggal_lahir")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .str.strptime(
                        pl.Date,
                        format="%Y-%m-%d",
                        strict=False
                    )
                    .alias("tanggal_lahir_master_clean"),
                pl.col("jenis_kelamin")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("jenis_kelamin_master_clean"),
                pl.col("nama_ibu")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("nama_ibu_master_clean"),
                pl.when(
                    pl.col("status_kematian")
                        .cast(pl.Utf8)
                        .str.to_lowercase()
                        .str.strip_chars()
                        .is_in([
                            "hidup",
                            "h"
                        ])
                )
                .then(pl.lit("h"))
                .when(
                    pl.col("status_kematian")
                        .cast(pl.Utf8)
                        .str.to_lowercase()
                        .str.strip_chars()
                        .is_in([
                            "meninggal",
                            "mati",
                            "wafat",
                            "m"
                        ])
                )
                .then(pl.lit("m"))
                .otherwise(None)
                .alias("status_hidup_master_clean")
            ])
        )
    
    def set_sync_status_in_progress(self, file_id):
        with self.engine.begin() as conn:
            conn.execute(self.sync_status_in_progress_query,{
                    "file_id": file_id
                })
    
    def insert_institution(self, insert_query, results, matched_time_query, matching_time_ms, file_id, sync_status):
        with self.engine.begin() as conn:
            conn.execute(insert_query,results)
            conn.execute(matched_time_query,{
                    "matching_time_ms": matching_time_ms,
                    "file_id": file_id
                })
            conn.execute(self.sync_status_query,{
                    "sync_status": sync_status,
                    "file_id": file_id
                })
            
    def insert_manual_review(self, rows):
        with self.engine.begin() as conn:
            conn.execute(self.manual_review_insert_query, rows)