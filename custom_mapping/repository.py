from sqlalchemy import text


# Kolom master yang layak dijadikan basis pairing (dipakai untuk matching
# identitas). Sengaja TIDAK termasuk `id` (surrogate key), `nama` (kolom legacy
# duplikat dari nama_lengkap di tabel master), dan `status_kematian` (kolom
# kategori status, bukan atribut identitas yang dibandingkan). Daftar ini
# sengaja dibuat konsisten dengan kolom yang dipakai
# StarrocksService.fetch_master_dataset() di processing/repository.py, supaya
# custom grading nantinya bisa reuse scoring engine (Jaro-Winkler) yang sama.
MASTER_MATCHING_COLUMNS = [
    "nik",
    "nama_lengkap",
    "tempat_lahir",
    "tanggal_lahir",
    "jenis_kelamin",
    "nama_ibu",
    "provinsi",
    "kabupaten",
    "kecamatan",
    "kelurahan",
]


class CustomMappingRepository:
    def __init__(self, engine):
        self.engine = engine
        print("Custom Mapping Repository Initialized!")

    def get_uploaded_file(self, file_id):
        query = text("""
            SELECT
                file_id,
                minio_path,
                grade,
                is_custom_ready,
                custom_mapping_task_status
            FROM uploaded_files
            WHERE file_id = :file_id
        """)
        with self.engine.connect() as conn:
            return conn.execute(query, {"file_id": file_id}).mappings().first()

    def get_active_mapping(self, file_id):
        query = text("""
            SELECT id, master_column, incoming_column, weight, confidence, source
            FROM custom_field_mapping
            WHERE file_id = :file_id AND is_active = 1
        """)
        with self.engine.connect() as conn:
            return conn.execute(query, {"file_id": file_id}).mappings().all()

    def deactivate_existing_mapping(self, file_id, source="GENAI"):
        """
        Nonaktifkan pairing lama sebelum insert pairing baru — dipakai saat
        regenerate via GenAI. Pairing yang sudah USER_EDITED sengaja TIDAK
        disentuh supaya perubahan manual user tidak hilang oleh regenerate GenAI.
        """
        query = text("""
            UPDATE custom_field_mapping
            SET is_active = 0, updated_at = NOW()
            WHERE file_id = :file_id AND source = :source AND is_active = 1
        """)
        with self.engine.begin() as conn:
            conn.execute(query, {"file_id": file_id, "source": source})

    def deactivate_all_active(self, file_id):
        """
        Nonaktifkan SEMUA pairing aktif (GENAI maupun USER_EDITED) — dipakai
        pas user save final pairing di step 7 (PUT /custom-mapping/{file_id}),
        karena submission itu dianggap pengganti penuh dari state sebelumnya.
        """
        query = text("""
            UPDATE custom_field_mapping
            SET is_active = 0, updated_at = NOW()
            WHERE file_id = :file_id AND is_active = 1
        """)
        with self.engine.begin() as conn:
            conn.execute(query, {"file_id": file_id})

    def insert_mapping_rows(self, rows):
        if not rows:
            return
        query = text("""
            INSERT INTO custom_field_mapping (
                file_id, master_column, incoming_column, weight, confidence, source, is_active
            ) VALUES (
                :file_id, :master_column, :incoming_column, :weight, :confidence, :source, 1
            )
        """)
        with self.engine.begin() as conn:
            conn.execute(query, rows)

    def set_is_custom_ready(self, file_id: str, ready: bool):
        query = text("""
            UPDATE uploaded_files
            SET is_custom_ready = :ready
            WHERE file_id = :file_id
        """)
        with self.engine.begin() as conn:
            conn.execute(query, {"file_id": file_id, "ready": 1 if ready else 0})

    def force_set_grade_6(self, file_id: str):
        """
        Dipakai saat user klik tombol 'custom grading' secara manual pada file
        yang belum/sudah kepgrade lain — override paksa ke grade 6. Kalau
        file sudah auto-graded 6 oleh grader_service (fallback grade F),
        endpoint pemanggil skip UPDATE ini (lihat routes.py).
        """
        query = text("""
            UPDATE uploaded_files
            SET grade = 6
            WHERE file_id = :file_id
        """)
        with self.engine.begin() as conn:
            conn.execute(query, {"file_id": file_id})

    def set_custom_mapping_task_info(self, file_id: str, task_id: str | None, status: str):
        # Pola sama seperti StarrocksService.set_matching_task_info di
        # processing/repository.py: query terpisah untuk task_id None vs terisi,
        # supaya update status berkala tidak menimpa task_id yang sudah tersimpan.
        with self.engine.begin() as conn:
            if task_id is not None:
                conn.execute(
                    text("""
                        UPDATE uploaded_files
                        SET custom_mapping_task_status = :status,
                            custom_mapping_task_id = :task_id
                        WHERE file_id = :file_id
                    """),
                    {"file_id": file_id, "task_id": task_id, "status": status},
                )
            else:
                conn.execute(
                    text("""
                        UPDATE uploaded_files
                        SET custom_mapping_task_status = :status
                        WHERE file_id = :file_id
                    """),
                    {"file_id": file_id, "status": status},
                )