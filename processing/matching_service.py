import time
from io import BytesIO
import duckdb
import tempfile
import polars as pl
from rapidfuzz.distance import JaroWinkler
from sqlalchemy import text

class MatchingService:

    def __init__(self, engine, minio_client, bucket_name):
        self.BATCH_SIZE = 1000
        self.engine = engine
        self.minio_client = minio_client
        self.bucket_name = bucket_name

    def normalize_string(self, value):

        if value is None:
            return ""

        return (
            str(value)
            .strip()
            .lower()
        )

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
    
    def load_parquet_from_minio(self, object_name):

        response = self.minio_client.get_object(
            self.bucket_name,
            object_name
        )

        with tempfile.NamedTemporaryFile(suffix=".parquet") as tmp:
            for chunk in response.stream(32 * 1024):
                tmp.write(chunk)

            tmp.flush()

            df = pl.read_parquet(tmp.name)

        df.columns = [
            c.strip().lower()
            for c in df.columns
        ]

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

    def process_grade_a(self, file_id):

        uploaded_file = self.get_uploaded_file(file_id)

        if not uploaded_file:
            raise Exception("File ID not found")

        if uploaded_file["grade"] != "A":
            raise Exception(
                "This endpoint only processes Grade A files"
            )

        incoming_df = self.load_parquet_from_minio(
            uploaded_file["minio_path"]
        )
        print(f"Incoming rows: {incoming_df.height}")

        master_df = self.fetch_master_dataset()
        print(f"Master rows fetched: {master_df.height}")

        start = time.perf_counter()
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

        results = []

        for row in joined_df.iter_rows(named=True):
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
        matching_time_ms = round((time.perf_counter() - start) * 1000, 2)
        print(f"Results prepared: {len(results)}")

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

        matched_time_query = text("""
            UPDATE uploaded_files
            SET matching_time_ms = :matching_time_ms
            WHERE file_id = :file_id
        """)
        
        with self.engine.begin() as conn:

            for i in range(0, len(results), self.BATCH_SIZE):

                batch = results[i:i + self.BATCH_SIZE]

                conn.execute(
                    insert_query,
                    batch
                )

                print(f"Inserted {i + len(batch)} rows")

            conn.execute(
                matched_time_query,
                {
                    "matching_time_ms": matching_time_ms,
                    "file_id": file_id
                }
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