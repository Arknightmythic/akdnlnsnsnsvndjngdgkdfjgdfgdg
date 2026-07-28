import polars as pl
from sqlalchemy import text


class StarrocksService:
    def __init__(self, engine):
        self.engine = engine

    def load_matching_query(self, grade):
        query = text("""
            SELECT matching_query
            FROM matching_queries
            WHERE grade_code = :grade
        """)
        with self.engine.connect() as conn:
            result = conn.execute(query, {"grade": grade}).mappings().first()

        if result is None:
            raise ValueError(f"No matching query found for grade {grade}")

        return result["matching_query"]

    def load_grade_rules(self):
        query = text("""
            SELECT
                grade_code,
                auto_missing_max,
                auto_score_min,
                review_missing_count,
                review_score_min,
                review_score_max
            FROM grade_rules
        """)
        with self.engine.connect() as conn:
            rows = conn.execute(query).mappings().all()

        return {row["grade_code"]: dict(row) for row in rows}

    def get_uploaded_file(self, file_id):
        query = text("""
            SELECT
                file_id,
                minio_path,
                upload_timestamp,
                grade,
                matching_task_status,
                sync_status,
                is_sync,
                is_custom_ready
            FROM uploaded_files
            WHERE file_id = :file_id
        """)
        with self.engine.connect() as conn:
            result = conn.execute(query, {"file_id": file_id}).mappings().first()

        return result

    def fetch_master_dataset(self):
        query = text("""
            SELECT nik, nama_lengkap, tempat_lahir, provinsi, kabupaten, kecamatan,
                   kelurahan, tanggal_lahir, jenis_kelamin, nama_ibu, status_kematian
            FROM master
        """)
        with self.engine.connect() as conn:
            rows = conn.execute(query).mappings().all()

        return (
            pl.DataFrame(rows)
            .with_columns([
                pl.col("nik").cast(pl.Utf8),
                pl.col("nama_lengkap").cast(pl.Utf8).str.to_lowercase().str.strip_chars().alias("nama_master_clean"),
                pl.col("tempat_lahir").cast(pl.Utf8).str.to_lowercase().str.strip_chars().alias("tempat_lahir_master_clean"),
                pl.col("provinsi").cast(pl.Utf8).str.to_lowercase().str.strip_chars().alias("provinsi_master_clean"),
                pl.col("kabupaten").cast(pl.Utf8).str.to_lowercase().str.strip_chars().alias("kabupaten_master_clean"),
                pl.col("kecamatan").cast(pl.Utf8).str.to_lowercase().str.strip_chars().alias("kecamatan_master_clean"),
                pl.col("kelurahan").cast(pl.Utf8).str.to_lowercase().str.strip_chars().alias("kelurahan_master_clean"),
                pl.col("tanggal_lahir").cast(pl.Utf8).str.to_lowercase().str.strip_chars()
                    .str.strptime(pl.Date, format="%Y-%m-%d", strict=False)
                    .alias("tanggal_lahir_master_clean"),
                pl.col("jenis_kelamin").cast(pl.Utf8).str.to_lowercase().str.strip_chars().alias("jenis_kelamin_master_clean"),
                pl.col("nama_ibu").cast(pl.Utf8).str.to_lowercase().str.strip_chars().alias("nama_ibu_master_clean"),
                pl.when(
                    pl.col("status_kematian").cast(pl.Utf8).str.to_lowercase().str.strip_chars().is_in(["hidup", "h"])
                )
                .then(pl.lit("h"))
                .when(
                    pl.col("status_kematian").cast(pl.Utf8).str.to_lowercase().str.strip_chars().is_in(["meninggal", "mati", "wafat", "m"])
                )
                .then(pl.lit("m"))
                .otherwise(None)
                .alias("status_hidup_master_clean"),
            ])
        )

    def set_sync_status_in_progress(self, file_id):
        query = text("""
            UPDATE uploaded_files
            SET sync_status = 1
            WHERE file_id = :file_id
        """)
        with self.engine.begin() as conn:
            conn.execute(query, {"file_id": file_id})

    def insert_institution(self, insert_query, results, matched_time_query, matching_time_ms, file_id):
        print(f"Institution rows: {len(results)}")
        with self.engine.begin() as conn:
            conn.execute(insert_query, results)
            conn.execute(matched_time_query, {
                "matching_time_ms": matching_time_ms,
                "file_id": file_id,
            })

    def set_sync_complete(self, file_id, sync_status):
        query = text("""
            UPDATE uploaded_files
            SET is_sync = 1,
                sync_status = :sync_status
            WHERE file_id = :file_id
        """)
        with self.engine.begin() as conn:
            conn.execute(query, {"sync_status": sync_status, "file_id": file_id})

    def insert_manual_review(self, rows):
        print(f"Manual review rows: {len(rows)}")

        # jenis_kelamin_incoming HARUS ada di sini — sebelumnya kolom ini absen
        # dari INSERT sehingga selalu tersimpan NULL walau baris yang dikirim
        # (lihat matching_service_new.py) membawa nilainya. Akibatnya
        # PatternDetector di reasoning selalu menilai gender "kosong" dan
        # mencemari cache reasoning_patterns (lihat BUG_FIXING_GUIDE.md #4).
        query = text("""
            INSERT INTO manual_matches (
                file_id, id_incoming, nik_incoming, nama_incoming,
                tempat_lahir_incoming, area_incoming, tanggal_lahir_incoming,
                jenis_kelamin_incoming, nama_ibu_incoming
            )
            VALUES (
                :file_id, :id_incoming, :nik_incoming, :nama_incoming,
                :tempat_lahir_incoming, :area_incoming, :tanggal_lahir_incoming,
                :jenis_kelamin_incoming, :nama_ibu_incoming
            )
        """)

        with self.engine.begin() as conn:
            for i in range(0, len(rows), 5000):
                batch = rows[i:i + 5000]
                print(f"Inserting manual review batch {i // 5000 + 1}, size={len(batch)}")
                conn.execute(query, batch)

    # FIX #7: Ganti template string Python di dalam SQL string yang fragile dan rawan error.
    # Sebelumnya pakai pola f-string + str.replace() untuk kondisional kolom,
    # yang bisa RuntimeError jika task_id=None dan string replacement meleset.
    # Solusi: dua query terpisah yang jelas — satu dengan task_id, satu tanpa.
    def set_matching_task_info(self, file_id: str, task_id: str | None, status: str):
        with self.engine.begin() as conn:
            if task_id is not None:
                # Update status DAN task_id sekaligus
                conn.execute(
                    text("""
                        UPDATE uploaded_files
                        SET matching_task_status = :status,
                            matching_task_id = :task_id
                        WHERE file_id = :file_id
                    """),
                    {"file_id": file_id, "task_id": task_id, "status": status},
                )
            else:
                # Update status saja, jangan sentuh task_id yang sudah ada
                conn.execute(
                    text("""
                        UPDATE uploaded_files
                        SET matching_task_status = :status
                        WHERE file_id = :file_id
                    """),
                    {"file_id": file_id, "status": status},
                )

    def start_new_matching_run(self, file_id: str):
        """
        Dipanggil SEBELUM apply_async(), menggantikan set_matching_task_info()
        untuk kasus start matching. Selain menandai matching_task_status
        PROCESSING, kolom-kolom lain yang merupakan jejak RUN SEBELUMNYA juga
        di-reset dalam UPDATE yang sama:

        - reasoning_task_status -> 'IDLE' (kalau tidak, file yang di-re-match
          setelah sebelumnya pernah selesai akan menunjukkan matching_task_status
          PROCESSING berdampingan dengan reasoning_task_status SUCCESS yang
          sebenarnya sisa run lama — kombinasi yang membingungkan dan salah).
        - preview_url / investigate_url -> NULL (kalau tidak, keduanya masih
          menunjuk ke hasil matching run SEBELUMNYA selama run baru berjalan —
          siapa pun yang membuka link itu di tengah proses akan melihat data
          basi, bukan error atau data terbaru).
        - export_status -> 'IDLE' (file export lama sudah tidak merepresentasikan
          hasil matching yang baru; men-download-nya harus diblok sampai export
          baru selesai, bukan diam-diam menyajikan CSV lama).

        Semua ini harus terjadi SEBELUM dispatch ke Celery, dengan alasan yang
        sama seperti kenapa matching_task_status di-set PROCESSING sebelum
        apply_async(): mencegah race kalau worker sempat lebih cepat menulis
        ulang kolom-kolom ini (mis. reasoning yang sudah selesai duluan untuk
        file kecil) sebelum reset ini sempat jalan.
        """
        query = text("""
            UPDATE uploaded_files
            SET matching_task_status = 'PROCESSING',
                reasoning_task_status = 'IDLE',
                reasoning_task_id = NULL,
                preview_url = NULL,
                investigate_url = NULL,
                export_status = 'IDLE'
            WHERE file_id = :file_id
        """)
        with self.engine.begin() as conn:
            conn.execute(query, {"file_id": file_id})

    def set_matching_task_id(self, file_id: str, task_id: str):
        """
        Update HANYA matching_task_id, tanpa menyentuh matching_task_status.

        Dipakai di processing/routes.py SETELAH apply_async(): pada saat itu
        worker mungkin sudah selesai duluan (file kecil) dan sudah menulis
        status SUCCESS/FAILED. Kalau kita ikut menimpa status di sini juga,
        status final itu bisa balik tertulis PROCESSING selamanya — itulah
        race condition yang diperbaiki (lihat BUG_FIXING_GUIDE.md #7).
        """
        query = text("""
            UPDATE uploaded_files
            SET matching_task_id = :task_id
            WHERE file_id = :file_id
        """)
        with self.engine.begin() as conn:
            conn.execute(query, {"file_id": file_id, "task_id": task_id})