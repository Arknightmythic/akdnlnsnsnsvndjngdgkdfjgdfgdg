import time
from io import BytesIO
import duckdb
import tempfile
import polars as pl
from rapidfuzz.distance import JaroWinkler
from sqlalchemy import text
from .string_similarity import ScoringService

class MatchingService:
    def __init__(self, engine, minio_client, bucket_name):
        self.BATCH_SIZE = 10000
        self.engine = engine
        self.minio_client = minio_client
        self.bucket_name = bucket_name
        self.scoring_service = ScoringService()

    def normalize_string(self, value):
        if value is None:
            return ""

        return (str(value).strip().lower())

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

    def load_csv_from_minio(self, object_name):
        response = self.minio_client.get_object(
            self.bucket_name,
            object_name
        )

        file_bytes = response.read()
        df = pl.read_csv(BytesIO(file_bytes))
        df.columns = [c.strip().lower() for c in df.columns]

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

        df.columns = [c.strip().lower()for c in df.columns]

        expressions = []
        if "id" in df.columns:
            expressions.append(
                pl.col("id")
                    .cast(pl.Utf8)
                    .str.strip_chars()
            )

        if "nik" in df.columns:
            expressions.append(
                pl.col("nik")
                    .cast(pl.Utf8)
                    .str.strip_chars()
            )

        if "nama" in df.columns:
            expressions.append(
                pl.col("nama")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("nama_clean")
            )

        if "tempat_lahir" in df.columns:
            expressions.append(
                pl.col("tempat_lahir")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("tempat_lahir_clean")
            )

        if "provinsi" in df.columns:
            expressions.append(
                pl.col("provinsi")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("provinsi_clean")
            )

        if "kabupaten" in df.columns:
            expressions.append(
                pl.col("kabupaten")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("kabupaten_clean")
            )

        if "kecamatan" in df.columns:
            expressions.append(
                pl.col("kecamatan")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("kecamatan_clean")
            )

        if "kelurahan" in df.columns:
            expressions.append(
                pl.col("kelurahan")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("kelurahan_clean")
            )

        if "tanggal_lahir" in df.columns:
            raw_tanggal = (
                pl.col("tanggal_lahir")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
            )

            expressions.append(

                pl.coalesce([
                    raw_tanggal.str.strptime(
                        pl.Date,
                        format="%d/%m/%Y",
                        strict=False
                    ),
                    raw_tanggal.str.strptime(
                        pl.Date,
                        format="%d-%m-%Y",
                        strict=False
                    ),
                    raw_tanggal.str.strptime(
                        pl.Date,
                        format="%d %m %Y",
                        strict=False
                    ),
                    raw_tanggal.str.strptime(
                        pl.Date,
                        format="%d-%b-%Y",
                        strict=False
                    ),
                    raw_tanggal.str.strptime(
                        pl.Date,
                        format="%d %B %Y",
                        strict=False
                    ),
                    raw_tanggal.str.strptime(
                        pl.Date,
                        format="%Y-%m-%d",
                        strict=False
                    )

                ])
                .alias("tanggal_lahir_clean")
            )

        if "jenis_kelamin" in df.columns:
            expressions.append(
                pl.when(
                    pl.col("jenis_kelamin")
                        .cast(pl.Utf8)
                        .str.to_lowercase()
                        .str.strip_chars()
                        .is_in([
                            "laki-laki",
                            "laki laki",
                            "pria",
                            "male",
                            "l"
                        ])
                )
                .then(pl.lit("l"))

                .when(
                    pl.col("jenis_kelamin")
                        .cast(pl.Utf8)
                        .str.to_lowercase()
                        .str.strip_chars()
                        .is_in([
                            "perempuan",
                            "wanita",
                            "female",
                            "p"
                        ])
                )
                .then(pl.lit("p"))
                .otherwise(None)
                .alias("jenis_kelamin_clean")
            )

        if "status_hidup" in df.columns:
            expressions.append(
                pl.when(
                    pl.col("status_hidup")
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
                    pl.col("status_hidup")
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
                .alias("status_hidup_clean")
            )

        if "nama_ibu" in df.columns:
            expressions.append(
                pl.col("nama_ibu")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("nama_ibu_clean")
            )

        df = df.with_columns(expressions)
        df = df.with_columns(
            pl.when(
                pl.col("tanggal_lahir_clean")
                    .dt.year()
                    < 1900
            )
            .then(None)
            .otherwise(
                pl.col("tanggal_lahir_clean")
            )
            .alias("tanggal_lahir_clean")
        )

        return df

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

            score = self.scoring_service.safe_jaro(
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
        print(matching_time_ms)
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
            conn.execute(
                insert_query,
                results
            )

            conn.execute(
                matched_time_query,
                {
                    "matching_time_ms": matching_time_ms,
                    "file_id": file_id
                }
            )

        print("Batch insert completed")

        return {
            "message": "Grade A matching completed",
            "file_id": file_id,
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


    def count_missing_attributes(self, row):

        return sum([
            not row["nama_clean"],
            not row["tempat_lahir_clean"],
            not row["nama_ibu_clean"]
        ])

    def classify_grade_b_result(self, score, missing_count):
        if missing_count <= 1:
            if score >= 85:
                return "AUTO_MATCH"
            return "AUTO_UNMATCH"

        elif missing_count == 2:
            if 80 < score < 85:
                return "MANUAL_REVIEW"
            return "AUTO_UNMATCH"

        return "AUTO_UNMATCH"

    def process_grade_b(self, file_id):
        uploaded_file = self.get_uploaded_file(file_id)

        if not uploaded_file:
            raise Exception("File ID not found")

        if uploaded_file["grade"] != "B":
            raise Exception(
                "This endpoint only processes Grade B files"
            )

        incoming_df = self.load_parquet_from_minio(uploaded_file["minio_path"])
        print(f"Incoming rows: {incoming_df.height}")

        master_df = self.fetch_master_dataset()
        print(f"Master rows fetched: {master_df.height}")

        start = time.perf_counter()
        con = duckdb.connect()
        con.register("incoming_df",incoming_df.to_arrow())

        con.register("master_df",master_df.to_arrow())

        joined_df = con.execute("""
            SELECT
                i.nik,
                i.nama,
                i.nama_clean,
                i.tempat_lahir,
                i.tempat_lahir_clean,
                i.nama_ibu,
                i.nama_ibu_clean,
                m.nik AS nik_master,
                m.nama_lengkap,
                m.nama_master_clean,
                m.tempat_lahir AS tempat_lahir_master,
                m.tempat_lahir_master_clean,
                m.nama_ibu AS nama_ibu_master,
                m.nama_ibu_master_clean
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
                    "match_result": "AUTO_UNMATCH",
                    "upload_date":
                        uploaded_file["upload_timestamp"]
                })
                continue

            missing_count = self.count_missing_attributes(row)

            score = round(
                self.scoring_service.compute_similarity_matched_grade_B(
                    row["nama_clean"],
                    row["nama_master_clean"],
                    row["tempat_lahir_clean"],
                    row["tempat_lahir_master_clean"],
                    row["nama_ibu_clean"],
                    row["nama_ibu_master_clean"]
                ),
                2
            )

            result = self.classify_grade_b_result(score, missing_count)

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

        print(matching_time_ms)
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
            conn.execute(insert_query,results)

            conn.execute(
                matched_time_query,
                {
                    "matching_time_ms": matching_time_ms,
                    "file_id": file_id
                }
            )

        print("Batch insert completed")

        return {
            "message": "Grade B matching completed",
            "file_id": file_id,
            "processed_rows": len(results),
            "matched_rows": sum(
                1
                for r in results
                if r["match_result"] == "AUTO_MATCH"
            ),
            "manual_review_rows": sum(
                1
                for r in results
                if r["match_result"] == "MANUAL_REVIEW"
            ),
            "unmatched_rows": sum(
                1
                for r in results
                if r["match_result"] == "AUTO_UNMATCH"
            )
        }
    
    def process_grade_c(self, file_id):
        uploaded_file = self.get_uploaded_file(file_id)

        if not uploaded_file:
            raise Exception("File ID not found")
        if uploaded_file["grade"] != "C":
            raise Exception(
                "This endpoint only processes Grade C files"
            )
        incoming_df = self.load_parquet_from_minio(uploaded_file["minio_path"])
        print(f"Incoming rows: {incoming_df.height}")

        master_df = self.fetch_master_dataset()
        print(f"Master rows fetched: {master_df.height}")

        start = time.perf_counter()
        con = duckdb.connect()

        con.register("incoming_df",incoming_df.to_arrow())
        con.register("master_df",master_df.to_arrow())

        candidate_query = """
            SELECT
                i.id AS nik_incoming,
                i.nama,
                i.nama_clean,
                i.tempat_lahir,
                i.tempat_lahir_clean,
                i.tanggal_lahir_clean,
                i.jenis_kelamin_clean,
                m.nik AS nik_master,
                m.nama_lengkap,
                m.nama_master_clean,
                m.tempat_lahir AS tempat_lahir_master,
                m.tempat_lahir_master_clean,
                m.tanggal_lahir_master_clean AS tanggal_lahir_master_clean,
                m.jenis_kelamin_master_clean AS jenis_kelamin_master_clean
            FROM incoming_df i
            LEFT JOIN master_df m
                ON i.jenis_kelamin_clean =
                m.jenis_kelamin_master_clean
                AND EXTRACT(
                    DAY FROM CAST(i.tanggal_lahir_clean AS DATE)
                ) = EXTRACT(
                    DAY FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                )
                AND EXTRACT(
                    MONTH FROM CAST(i.tanggal_lahir_clean AS DATE)
                ) = EXTRACT(
                    MONTH FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                )
                AND LEFT(i.nama_clean, 3) =
                    LEFT(m.nama_master_clean, 3)
        """

        candidate_df = con.execute(candidate_query).pl()
        print(f"Candidate rows: {candidate_df.height}")

        results_map = {}

        for row in candidate_df.iter_rows(named=True):
            nik_incoming = row["nik_incoming"]
            if row["nik_master"] is None:
                if nik_incoming not in results_map:
                    results_map[nik_incoming] = {
                        "score": 0,
                        "result": "AUTO_UNMATCH",
                        "nik_master": None
                    }

                continue

            nama_score = self.scoring_service.safe_jaro(
                row["nama_clean"],
                row["nama_master_clean"]
            )
            tempat_lahir_score = self.scoring_service.safe_jaro(
                row["tempat_lahir_clean"],
                row["tempat_lahir_master_clean"]
            )
            tanggal_lahir_score = (
                1.0
                if row["tanggal_lahir_clean"] ==
                row["tanggal_lahir_master_clean"]
                else 0.0
            )
            final_score = (
                nama_score * 0.6 +
                tempat_lahir_score * 0.2 +
                tanggal_lahir_score * 0.2
            )

            existing = results_map.get(nik_incoming)

            if (existing is None or final_score > existing["score"]):
                if final_score >= 0.87:
                    result = "AUTO_MATCH"
                elif final_score >= 0.85:
                    result = "MANUAL_REVIEW"
                else:
                    result = "AUTO_UNMATCH"
                results_map[nik_incoming] = {
                    "score": final_score,
                    "result": result,
                    "nik_master": row["nik_master"]
                }

        results = []

        for nik_incoming, best_match in results_map.items():
            results.append({
                "nik_incoming": nik_incoming,
                "nik_master": best_match["nik_master"],
                "file_id": file_id,
                "match_score": round(best_match["score"] * 100,2),
                "match_result": best_match["result"],
                "upload_date": uploaded_file["upload_timestamp"]
            })

        matching_time_ms = round((time.perf_counter() - start) * 1000,2)
        print(f"Matching time: {matching_time_ms} ms")
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
            conn.execute(
                insert_query,
                results
            )
            conn.execute(
                matched_time_query,
                {
                    "matching_time_ms": matching_time_ms,
                    "file_id": file_id
                }
            )

        print("Batch insert completed")
        return {
            "message": "Grade C matching completed",
            "file_id": file_id,
            "processed_rows": len(results),
            "matched_rows": sum(
                1
                for r in results
                if r["match_result"] == "AUTO_MATCH"
            ),
            "manual_review_rows": sum(
                1
                for r in results
                if r["match_result"] == "MANUAL_REVIEW"
            ),
            "unmatched_rows": sum(
                1
                for r in results
                if r["match_result"] == "AUTO_UNMATCH"
            )
        }
    
    def process_grade_d(self, file_id):
        uploaded_file = self.get_uploaded_file(file_id)

        if not uploaded_file:
            raise Exception("File ID not found")
        if uploaded_file["grade"] != "D":
            raise Exception(
                "This endpoint only processes Grade D files"
            )

        incoming_df = self.load_parquet_from_minio(
            uploaded_file["minio_path"]
        )
        incoming_df = incoming_df.with_row_index(
            name="incoming_row_id"
        )
        print(f"Incoming rows: {incoming_df.height}")

        master_df = self.fetch_master_dataset()
        print(f"Master rows fetched: {master_df.height}")

        start = time.perf_counter()
        con = duckdb.connect()
        con.register("incoming_df",incoming_df.to_arrow())
        con.register("master_df",master_df.to_arrow())

        candidate_query = """
            WITH missing_gender AS (
                SELECT
                    i.incoming_row_id,
                    i.nama_clean,
                    i.tempat_lahir_clean,
                    i.tanggal_lahir_clean,
                    i.nama_ibu_clean,
                    i.jenis_kelamin_clean,
                    m.nik AS nik_master,
                    m.nama_master_clean,
                    m.tempat_lahir_master_clean,
                    m.tanggal_lahir_master_clean,
                    m.nama_ibu_master_clean,
                    m.jenis_kelamin_master_clean
                FROM incoming_df i
                INNER JOIN master_df m
                    ON i.jenis_kelamin_clean IS NULL
                    AND i.tempat_lahir_clean IS NOT NULL
                    AND i.tempat_lahir_clean != ''
                    AND m.tempat_lahir_master_clean IS NOT NULL
                    AND m.tempat_lahir_master_clean != ''
                    AND LEFT(i.tempat_lahir_clean, 3)
                        =
                        LEFT(m.tempat_lahir_master_clean, 3)
                    AND EXTRACT(
                        DAY FROM CAST(i.tanggal_lahir_clean AS DATE)
                    )
                    =
                    EXTRACT(
                        DAY FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                    )
                    AND EXTRACT(
                        MONTH FROM CAST(i.tanggal_lahir_clean AS DATE)
                    )
                    =
                    EXTRACT(
                        MONTH FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                    )
            ),
            missing_tempat AS (
                SELECT
                    i.incoming_row_id,
                    i.nama_clean,
                    i.tempat_lahir_clean,
                    i.tanggal_lahir_clean,
                    i.nama_ibu_clean,
                    i.jenis_kelamin_clean,
                    m.nik AS nik_master,
                    m.nama_master_clean,
                    m.tempat_lahir_master_clean,
                    m.tanggal_lahir_master_clean,
                    m.nama_ibu_master_clean,
                    m.jenis_kelamin_master_clean
                FROM incoming_df i
                INNER JOIN master_df m
                    ON i.tempat_lahir_clean IS NULL
                    AND i.jenis_kelamin_clean =
                        m.jenis_kelamin_master_clean
                    AND i.nama_clean IS NOT NULL
                    AND i.nama_clean != ''
                    AND m.nama_master_clean IS NOT NULL
                    AND m.nama_master_clean != ''
                    AND LEFT(i.nama_clean, 3)
                        =
                        LEFT(m.nama_master_clean, 3)
                    AND EXTRACT(
                        DAY FROM CAST(i.tanggal_lahir_clean AS DATE)
                    )
                    =
                    EXTRACT(
                        DAY FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                    )
                    AND EXTRACT(
                        MONTH FROM CAST(i.tanggal_lahir_clean AS DATE)
                    )
                    =
                    EXTRACT(
                        MONTH FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                    )
            ),
            missing_tanggal AS (
                SELECT
                    i.incoming_row_id,
                    i.nama_clean,
                    i.tempat_lahir_clean,
                    i.tanggal_lahir_clean,
                    i.nama_ibu_clean,
                    i.jenis_kelamin_clean,
                    m.nik AS nik_master,
                    m.nama_master_clean,
                    m.tempat_lahir_master_clean,
                    m.tanggal_lahir_master_clean,
                    m.nama_ibu_master_clean,
                    m.jenis_kelamin_master_clean
                FROM incoming_df i
                INNER JOIN master_df m
                    ON i.tanggal_lahir_clean IS NULL
                    AND i.jenis_kelamin_clean =
                        m.jenis_kelamin_master_clean
                    AND i.tempat_lahir_clean IS NOT NULL
                    AND i.tempat_lahir_clean != ''
                    AND m.tempat_lahir_master_clean IS NOT NULL
                    AND m.tempat_lahir_master_clean != ''
                    AND LEFT(i.tempat_lahir_clean, 3)
                        =
                        LEFT(m.tempat_lahir_master_clean, 3)
                    AND i.nama_clean IS NOT NULL
                    AND i.nama_clean != ''
                    AND m.nama_master_clean IS NOT NULL
                    AND m.nama_master_clean != ''
                    AND LEFT(i.nama_clean, 3)
                        =
                        LEFT(m.nama_master_clean, 3)
            ),
            complete_data AS (
                SELECT
                    i.incoming_row_id,
                    i.nama_clean,
                    i.tempat_lahir_clean,
                    i.tanggal_lahir_clean,
                    i.nama_ibu_clean,
                    i.jenis_kelamin_clean,
                    m.nik AS nik_master,
                    m.nama_master_clean,
                    m.tempat_lahir_master_clean,
                    m.tanggal_lahir_master_clean,
                    m.nama_ibu_master_clean,
                    m.jenis_kelamin_master_clean
                FROM incoming_df i
                INNER JOIN master_df m
                    ON i.jenis_kelamin_clean =
                        m.jenis_kelamin_master_clean
                    AND LEFT(i.nama_clean, 3)
                        =
                        LEFT(m.nama_master_clean, 3)
                    AND EXTRACT(
                        DAY FROM CAST(i.tanggal_lahir_clean AS DATE)
                    )
                    =
                    EXTRACT(
                        DAY FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                    )
                    AND EXTRACT(
                        MONTH FROM CAST(i.tanggal_lahir_clean AS DATE)
                    )
                    =
                    EXTRACT(
                        MONTH FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                    )
            )
            SELECT DISTINCT *
            FROM (
                SELECT * FROM missing_gender
                UNION ALL
                SELECT * FROM missing_tempat
                UNION ALL
                SELECT * FROM missing_tanggal
                UNION ALL
                SELECT * FROM complete_data
            )
        """

        candidate_df = con.execute(candidate_query).pl()
        con.close()

        print(f"Candidate rows: {candidate_df.height}")
        results_map = {}

        for row in candidate_df.iter_rows(named=True):
            incoming_row_id = row["incoming_row_id"]
            if row["nik_master"] is None:
                if incoming_row_id not in results_map:
                    results_map[incoming_row_id] = {
                        "score": 0,
                        "result": "AUTO_UNMATCH",
                        "nik_master": None
                    }

                continue

            missing_count = 0

            if not row["tempat_lahir_clean"]:
                missing_count += 1
            if not row["tanggal_lahir_clean"]:
                missing_count += 1
            if not row["nama_ibu_clean"]:
                missing_count += 1

            weighted_score = 0
            active_weight = 0

            nama_score = self.scoring_service.safe_jaro(row["nama_clean"],row["nama_master_clean"])

            weighted_score += nama_score * 0.6
            active_weight += 0.6

            if row["tempat_lahir_clean"]:
                tempat_score = (
                    self.scoring_service.safe_jaro(
                        row["tempat_lahir_clean"],
                        row["tempat_lahir_master_clean"]
                    )
                )

                weighted_score += tempat_score * 0.05
                active_weight += 0.05

            if row["tanggal_lahir_clean"]:
                tanggal_score = (
                    1.0
                    if row["tanggal_lahir_clean"]
                    ==
                    row["tanggal_lahir_master_clean"]
                    else 0.0
                )

                weighted_score += tanggal_score * 0.3
                active_weight += 0.3

            if row["nama_ibu_clean"]:
                ibu_score = (
                    self.scoring_service.safe_jaro(
                        row["nama_ibu_clean"],
                        row["nama_ibu_master_clean"]
                    )
                )

                weighted_score += ibu_score * 0.05
                active_weight += 0.05

            final_score = (weighted_score / active_weight)

            if missing_count > 2:
                result = "AUTO_UNMATCH"
            elif (missing_count <= 1 and final_score >= 0.9):
                result = "AUTO_MATCH"
            elif (missing_count == 2 and 0.85 < final_score < 0.9):
                result = "MANUAL_REVIEW"
            elif final_score <= 0.85:
                result = "AUTO_UNMATCH"
            else:
                result = "AUTO_UNMATCH"
            existing = results_map.get(incoming_row_id)

            if (existing is None or final_score > existing["score"]):
                results_map[incoming_row_id] = {
                    "score": final_score,
                    "result": result,
                    "nik_master": row["nik_master"]
                }

        results = []

        for incoming_row_id, best_match in (results_map.items()):
            results.append({
                "nik_incoming": None,
                "nik_master": best_match["nik_master"],
                "file_id": file_id,
                "match_score": round(best_match["score"] * 100, 2),
                "match_result": best_match["result"],
                "upload_date": uploaded_file["upload_timestamp"]
            })

        matching_time_ms = round(
            (
                time.perf_counter() - start
            ) * 1000,
            2
        )

        print(f"Matching time: "f"{matching_time_ms} ms")
        print(f"Results prepared: "f"{len(results)}")

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

            SET matching_time_ms =
                :matching_time_ms

            WHERE file_id = :file_id
        """)

        with self.engine.begin() as conn:
            conn.execute(insert_query,results)
            conn.execute(
                matched_time_query,
                {
                    "matching_time_ms":
                        matching_time_ms,

                    "file_id":
                        file_id
                }
            )
        print("Batch insert completed")

        return {
            "message": "Grade D matching completed",
            "file_id": file_id,
            "processed_rows": len(results),
            "matched_rows":
                sum(
                    1
                    for r in results
                    if r["match_result"]
                    == "AUTO_MATCH"
                ),
            "manual_review_rows":
                sum(
                    1
                    for r in results
                    if r["match_result"]
                    == "MANUAL_REVIEW"
                ),
            "unmatched_rows":
                sum(
                    1
                    for r in results
                    if r["match_result"]
                    == "AUTO_UNMATCH"
                )
        }

    def process_grade_e(self, file_id):
        uploaded_file = self.get_uploaded_file(file_id)

        if not uploaded_file:
            raise Exception("File ID not found")
        if uploaded_file["grade"] != "E":
            raise Exception("This endpoint only processes Grade E files")

        incoming_df = self.load_parquet_from_minio(uploaded_file["minio_path"])
        incoming_df = incoming_df.with_row_index(name="incoming_row_id")
        print(f"Incoming rows: {incoming_df.height}")

        master_df = self.fetch_master_dataset()
        print(f"Master rows fetched: {master_df.height}")

        start = time.perf_counter()
        con = duckdb.connect()
        con.register("incoming_df",incoming_df.to_arrow())
        con.register("master_df",master_df.to_arrow())

        candidate_query = """
            WITH candidates AS (
                SELECT
                    i.incoming_row_id,
                    i.nama_clean,
                    i.tanggal_lahir_clean,
                    i.provinsi_clean,
                    i.kabupaten_clean,
                    i.kecamatan_clean,
                    i.kelurahan_clean,
                    i.nama_ibu_clean,
                    i.status_hidup_clean,
                    m.nik AS nik_master,
                    m.nama_master_clean,
                    m.tanggal_lahir_master_clean,
                    m.provinsi_master_clean,
                    m.kabupaten_master_clean,
                    m.kecamatan_master_clean,
                    m.kelurahan_master_clean,
                    m.nama_ibu_master_clean,
                    m.status_hidup_master_clean
                FROM incoming_df i
                INNER JOIN master_df m
                    ON i.status_hidup_clean =
                        m.status_hidup_master_clean
                    AND i.nama_clean IS NOT NULL
                    AND i.nama_clean != ''
                    AND m.nama_master_clean IS NOT NULL
                    AND m.nama_master_clean != ''
                    AND LEFT(i.nama_clean, 3)
                        =
                        LEFT(m.nama_master_clean, 3)
                    AND i.tanggal_lahir_clean IS NOT NULL
                    AND m.tanggal_lahir_master_clean
                        IS NOT NULL
                    AND EXTRACT(
                        DAY FROM CAST(
                            i.tanggal_lahir_clean AS DATE
                        )
                    )
                    =
                    EXTRACT(
                        DAY FROM CAST(
                            m.tanggal_lahir_master_clean
                            AS DATE
                        )
                    )
                    AND EXTRACT(
                        MONTH FROM CAST(
                            i.tanggal_lahir_clean AS DATE
                        )
                    )
                    =
                    EXTRACT(
                        MONTH FROM CAST(
                            m.tanggal_lahir_master_clean
                            AS DATE
                        )
                    )
            )
            SELECT DISTINCT *
            FROM candidates
        """

        candidate_df = con.execute(
            candidate_query
        ).pl()
        con.close()
        print(f"Candidate rows: {candidate_df.height}")

        results_map = {}
        for row in candidate_df.iter_rows(named=True):
            incoming_row_id = row["incoming_row_id"]
            if row["nik_master"] is None:
                if incoming_row_id not in results_map:
                    results_map[incoming_row_id] = {
                        "score": 0,
                        "result": "AUTO_UNMATCH",
                        "nik_master": None
                    }

                continue

            missing_count = 0
            if (not row["nama_clean"]):
                missing_count += 1
            if (not row["tanggal_lahir_clean"]):
                missing_count += 1
            area_exists = any([
                row["provinsi_clean"],
                row["kabupaten_clean"],
                row["kecamatan_clean"],
                row["kelurahan_clean"]
            ])
            if not area_exists:
                missing_count += 1
            if (not row["nama_ibu_clean"]):
                missing_count += 1

            weighted_score = 0
            active_weight = 0

            if row["nama_clean"]:
                nama_score = (
                    self.scoring_service.safe_jaro(
                        row["nama_clean"],
                        row["nama_master_clean"]
                    )
                )
                weighted_score += nama_score * 0.5
                active_weight += 0.5

            if row["tanggal_lahir_clean"]:
                tanggal_score = (
                    1.0
                    if row["tanggal_lahir_clean"]
                    ==
                    row["tanggal_lahir_master_clean"]
                    else 0.0
                )
                weighted_score += tanggal_score * 0.1
                active_weight += 0.1

            area_scores = []

            if (row["provinsi_clean"] and row["provinsi_master_clean"]):
                area_scores.append(
                    self.scoring_service.safe_jaro(
                        row["provinsi_clean"],
                        row["provinsi_master_clean"]
                    )
                )
            if (row["kabupaten_clean"] and row["kabupaten_master_clean"]):
                area_scores.append(
                    self.scoring_service.safe_jaro(
                        row["kabupaten_clean"],
                        row["kabupaten_master_clean"]
                    )
                )

            if (row["kecamatan_clean"] and row["kecamatan_master_clean"]):
                area_scores.append(
                    self.scoring_service.safe_jaro(
                        row["kecamatan_clean"],
                        row["kecamatan_master_clean"]
                    )
                )

            if (row["kelurahan_clean"] and row["kelurahan_master_clean"]):
                area_scores.append(
                    self.scoring_service.safe_jaro(
                        row["kelurahan_clean"],
                        row["kelurahan_master_clean"]
                    )
                )

            if len(area_scores) > 0:
                area_score = (sum(area_scores) / len(area_scores))
                weighted_score += area_score * 0.3
                active_weight += 0.3

            if row["nama_ibu_clean"]:
                ibu_score = (
                    self.scoring_service.safe_jaro(
                        row["nama_ibu_clean"],
                        row["nama_ibu_master_clean"]
                    )
                )
                weighted_score += ibu_score * 0.1
                active_weight += 0.1

            final_score = (weighted_score / active_weight if active_weight > 0 else 0)

            if (missing_count > 2 or final_score <= 0.8):
                result = "AUTO_UNMATCH"
            elif (missing_count <= 1 and final_score >= 0.81):
                result = "AUTO_MATCH"
            elif (missing_count == 2 and final_score > 0.8 and final_score < 0.81):
                result = "MANUAL_REVIEW"
            else:
                result = "AUTO_UNMATCH"

            existing = results_map.get(incoming_row_id)

            if (existing is None or final_score > existing["score"]):
                results_map[incoming_row_id] = {
                    "score": final_score,
                    "result": result,
                    "nik_master": row["nik_master"]
                }

        all_incoming_ids = set(incoming_df["incoming_row_id"].to_list())
        matched_incoming_ids = set(results_map.keys())
        missing_incoming_ids = (all_incoming_ids - matched_incoming_ids)
        print(f"Rows without candidates: "f"{len(missing_incoming_ids)}")

        for incoming_row_id in missing_incoming_ids:
            results_map[incoming_row_id] = {
                "score": 0,
                "result": "AUTO_UNMATCH",
                "nik_master": None
            }

        results = []
        for incoming_row_id, best_match in (results_map.items()):
            results.append({
                "nik_incoming": None,
                "nik_master": best_match["nik_master"],
                "file_id": file_id,
                "match_score":
                    round(
                        best_match["score"] * 100,
                        2
                    ),
                "match_result":
                    best_match["result"],
                "upload_date":
                    uploaded_file[
                        "upload_timestamp"
                    ]
            })

        matching_time_ms = round(
            (
                time.perf_counter() - start
            ) * 1000,
            2
        )

        print(f"Matching time: "f"{matching_time_ms} ms")
        print(f"Results prepared: "f"{len(results)}")

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
            SET matching_time_ms =
                :matching_time_ms
            WHERE file_id = :file_id
        """)

        with self.engine.begin() as conn:
            conn.execute(insert_query,results)
            conn.execute(
                matched_time_query,
                {
                    "matching_time_ms":
                        matching_time_ms,
                    "file_id":
                        file_id
                }
            )
        print("Batch insert completed")

        return {
            "message": "Grade E matching completed",
            "file_id": file_id,
            "processed_rows": len(results),
            "matched_rows":
                sum(
                    1
                    for r in results
                    if r["match_result"]
                    == "AUTO_MATCH"
                ),
            "manual_review_rows":
                sum(
                    1
                    for r in results
                    if r["match_result"]
                    == "MANUAL_REVIEW"
                ),
            "unmatched_rows":
                sum(
                    1
                    for r in results
                    if r["match_result"]
                    == "AUTO_UNMATCH"
                )
        }