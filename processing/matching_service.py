from io import BytesIO
import duckdb
import polars as pl
from rapidfuzz.distance import JaroWinkler
from sqlalchemy import text

class MatchingService:

    def __init__(self, engine, minio_client, bucket_name):

        self.engine = engine
        self.minio_client = minio_client
        self.bucket_name = bucket_name

    # =====================================================
    # NORMALIZATION
    # =====================================================

    def normalize_string(self, value):

        if value is None:
            return ""

        return (
            str(value)
            .strip()
            .lower()
        )

    # =====================================================
    # FILE METADATA
    # =====================================================

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

            result = conn.execute(
                query,
                {"file_id": file_id}
            ).mappings().first()

        return result

    # =====================================================
    # LOAD CSV FROM MINIO
    # =====================================================

    def load_csv_from_minio(self, object_name):

        response = self.minio_client.get_object(
            self.bucket_name,
            object_name
        )

        file_bytes = response.read()

        df = pl.read_csv(
            BytesIO(file_bytes)
        )

        df.columns = [
            c.strip().lower()
            for c in df.columns
        ]

        # vectorized normalization
        df = df.with_columns([
            pl.col("nik")
                .cast(pl.Utf8)
                .str.strip_chars(),

            pl.col("nama")
                .cast(pl.Utf8)
                .str.to_lowercase()
                .str.strip_chars()
                .alias("nama_clean")
        ])

        return df

    # =====================================================
    # BULK FETCH MASTER DATA
    # =====================================================

    def fetch_master_dataset(self):

        query = text("""
            SELECT
                nik,
                nama_lengkap
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
                    .alias("nama_master_clean")
            ])
        )

    # =====================================================
    # MAIN PROCESS
    # =====================================================

    def process_grade_a(self, file_id):

        uploaded_file = self.get_uploaded_file(file_id)

        if not uploaded_file:
            raise Exception("File ID not found")

        if uploaded_file["grade"] != "A":
            raise Exception(
                "This endpoint only processes Grade A files"
            )

        # =================================================
        # LOAD INCOMING CSV
        # =================================================

        incoming_df = self.load_csv_from_minio(
            uploaded_file["minio_path"]
        )

        print(f"Incoming rows: {incoming_df.height}")

        # =================================================
        # BULK LOAD MASTER DATA
        # =================================================

        master_df = self.fetch_master_dataset()

        print(f"Master rows fetched: {master_df.height}")

        # =================================================
        # DUCKDB JOIN
        # =================================================

        con = duckdb.connect()

        con.register(
            "incoming_df",
            incoming_df.to_arrow()
        )

        con.register(
            "master_df",
            master_df.to_arrow()
        )

        joined_df = con.execute("""
            SELECT
                i.nik,
                i.nama,
                i.nama_clean,

                m.nik AS nik_master,
                m.nama_lengkap,
                m.nama_master_clean

            FROM incoming_df i

            LEFT JOIN master_df m
                ON i.nik = m.nik
        """).pl()

        print(f"Joined rows: {joined_df.height}")

        # =================================================
        # MATCHING
        # =================================================

        results = []

        for row in joined_df.iter_rows(named=True):

            # =============================
            # NO MATCH
            # =============================

            if row["nik_master"] is None:

                results.append({
                    "nik_incoming": row["nik"],
                    "nik_master": None,
                    "file_id": file_id,
                    "match_score": 0,
                    "match_result": "NO_NIK_MATCH",
                    "upload_date":
                        uploaded_file["upload_timestamp"]
                })

                continue

            # =============================
            # JARO WINKLER
            # =============================

            score = JaroWinkler.similarity(
                row["nama_clean"],
                row["nama_master_clean"]
            )

            score = round(score * 100, 2)

            result = (
                "MATCHED"
                if score > 80
                else "LOW_NAME_SIMILARITY"
            )

            results.append({
                "nik_incoming": row["nik"],
                "nik_master": row["nik_master"],
                "file_id": file_id,
                "match_score": score,
                "match_result": result,
                "upload_date":
                    uploaded_file["upload_timestamp"]
            })

        print(f"Results prepared: {len(results)}")

        # =================================================
        # BATCH INSERT
        # =================================================

        insert_query = text("""
            INSERT INTO institution (
                nik_incoming,
                nik_master,
                file_id,
                match_score,
                match_result,
                upload_date
            )
            VALUES (
                :nik_incoming,
                :nik_master,
                :file_id,
                :match_score,
                :match_result,
                :upload_date
            )
        """)

        with self.engine.begin() as conn:

            conn.execute(
                insert_query,
                results
            )

        print("Batch insert completed")

        return {
            "processed_rows": len(results),
            "matched_rows": sum(
                1
                for r in results
                if r["match_result"] == "MATCHED"
            ),
            "unmatched_rows": sum(
                1
                for r in results
                if r["match_result"] == "NO_NIK_MATCH"
            )
        }