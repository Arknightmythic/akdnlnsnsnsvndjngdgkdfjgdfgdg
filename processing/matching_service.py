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

        expressions = []

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

        if "tanggal_lahir" in df.columns:
            expressions.append(
                pl.coalesce([
                    pl.col("tanggal_lahir")
                        .cast(pl.Utf8)
                        .str.strip_chars()
                        .str.strptime(
                            pl.Date,
                            format="%d-%m-%Y",
                            strict=False
                        ),

                    pl.col("tanggal_lahir")
                        .cast(pl.Utf8)
                        .str.strip_chars()
                        .str.strptime(
                            pl.Date,
                            format="%d-%m-%y",
                            strict=False
                        )
                ]).alias("tanggal_lahir_clean")
            )

        # jenis kelamin
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

        # nama ibu
        if "nama_ibu" in df.columns:
            expressions.append(
                pl.col("nama_ibu")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("nama_ibu_clean")
            )

        df = df.with_columns(expressions)

        return df

    def fetch_master_dataset(self):

        query = text("""
            SELECT
                nik,
                nama_lengkap,
                tempat_lahir,
                tanggal_lahir,
                jenis_kelamin,
                nama_ibu
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
                    .alias("nama_ibu_master_clean")
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

            result = self.classify_grade_b_result(
                score,
                missing_count
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

        incoming_df = self.load_parquet_from_minio(
            uploaded_file["minio_path"]
        )

        # Grade C has no NIK
        # create surrogate key per incoming row
        incoming_df = incoming_df.with_row_index(
            name="incoming_row_id"
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

        candidate_query = """
            SELECT
                i.incoming_row_id,

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

            incoming_row_id = row["incoming_row_id"]

            # no candidate found
            if row["nik_master"] is None:

                if incoming_row_id not in results_map:

                    results_map[incoming_row_id] = {
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

            existing = results_map.get(
                incoming_row_id
            )

            # keep ONLY highest scoring candidate
            if (
                existing is None or
                final_score > existing["score"]
            ):

                if final_score >= 0.87:
                    result = "AUTO_MATCH"

                elif final_score >= 0.85:
                    result = "MANUAL_REVIEW"

                else:
                    result = "AUTO_UNMATCH"

                results_map[incoming_row_id] = {
                    "score": final_score,
                    "result": result,
                    "nik_master": row["nik_master"]
                }

        results = []

        for incoming_row_id, best_match in results_map.items():

            results.append({
                "nik_incoming": None,

                "nik_master": best_match["nik_master"],

                "file_id": file_id,

                "match_score": round(
                    best_match["score"] * 100,
                    2
                ),

                "match_result": best_match["result"],

                "upload_date":
                    uploaded_file["upload_timestamp"]
            })

        matching_time_ms = round(
            (time.perf_counter() - start) * 1000,
            2
        )

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

        start = time.perf_counter()

        incoming_df = self.load_parquet_from_minio(
            uploaded_file["minio_path"]
        )

        incoming_df = (
            incoming_df
            .with_row_index(name="incoming_row_id")
            .with_columns([
                pl.col("nama_clean")
                    .fill_null(""),

                pl.col("tempat_lahir_clean")
                    .fill_null(""),

                pl.col("tanggal_lahir_clean")
                    .fill_null(""),

                pl.col("nama_ibu_clean")
                    .fill_null(""),

                pl.col("jenis_kelamin_clean")
                    .fill_null(""),

                pl.col("nama_clean")
                    .str.slice(0, 3)
                    .alias("nama_prefix_3"),

                pl.col("nama_ibu_clean")
                    .str.slice(0, 3)
                    .alias("ibu_prefix_3"),

                pl.col("tanggal_lahir_clean")
                    .dt.day()
                    .alias("birth_day"),

                pl.col("tanggal_lahir_clean")
                    .dt.month()
                    .alias("birth_month")
            ])
        )

        print(f"Incoming rows: {incoming_df.height}")

        master_df = self.fetch_master_dataset()

        master_df = (
            master_df
            .with_columns([
                pl.col("nama_master_clean")
                    .fill_null(""),

                pl.col("tempat_lahir_master_clean")
                    .fill_null(""),

                pl.col("tanggal_lahir_master_clean")
                    .fill_null(""),

                pl.col("nama_ibu_master_clean")
                    .fill_null(""),

                pl.col("jenis_kelamin_master_clean")
                    .fill_null(""),

                pl.col("nama_master_clean")
                    .str.slice(0, 3)
                    .alias("nama_prefix_3"),

                pl.col("nama_ibu_master_clean")
                    .str.slice(0, 3)
                    .alias("ibu_prefix_3"),

                pl.col("tanggal_lahir_master_clean")
                    .dt.day()
                    .alias("birth_day"),

                pl.col("tanggal_lahir_master_clean")
                    .dt.month()
                    .alias("birth_month")
            ])
        )

        print(f"Master rows fetched: {master_df.height}")

        con = duckdb.connect()

        con.register(
            "incoming_df",
            incoming_df.to_arrow()
        )

        con.register(
            "master_df",
            master_df.to_arrow()
        )

        candidate_query = """
            SELECT

                i.incoming_row_id,

                i.nama_clean,
                i.tempat_lahir_clean,
                i.tanggal_lahir_clean,
                i.nama_ibu_clean,

                m.nik AS nik_master,

                m.nama_master_clean,
                m.tempat_lahir_master_clean,
                m.tanggal_lahir_master_clean,
                m.nama_ibu_master_clean

            FROM incoming_df i

            INNER JOIN master_df m

                ON i.jenis_kelamin_clean =
                m.jenis_kelamin_master_clean

                AND (

                    (
                        i.birth_day = m.birth_day
                        AND
                        i.birth_month = m.birth_month
                    )

                    OR

                    (
                        i.nama_prefix_3 != ''
                        AND
                        m.nama_prefix_3 != ''
                        AND
                        i.nama_prefix_3 =
                        m.nama_prefix_3
                    )

                    OR

                    (
                        i.ibu_prefix_3 != ''
                        AND
                        m.ibu_prefix_3 != ''
                        AND
                        i.ibu_prefix_3 =
                        m.ibu_prefix_3
                    )
                )
        """

        candidate_df = con.execute(
            candidate_query
        ).pl()

        print(f"Candidate rows: {candidate_df.height}")

        if candidate_df.height == 0:

            return {
                "message": "No candidates found",
                "processed_rows": 0
            }

        candidate_df = candidate_df.with_columns([

            pl.struct([
                "nama_clean",
                "nama_master_clean"
            ])
            .map_elements(
                lambda x: self.scoring_service.safe_jaro(
                    x["nama_clean"],
                    x["nama_master_clean"]
                ),
                return_dtype=pl.Float64
            )
            .alias("nama_score"),

            pl.struct([
                "tempat_lahir_clean",
                "tempat_lahir_master_clean"
            ])
            .map_elements(
                lambda x: (
                    self.scoring_service.safe_jaro(
                        x["tempat_lahir_clean"],
                        x["tempat_lahir_master_clean"]
                    )
                    if x["tempat_lahir_clean"]
                    else None
                ),
                return_dtype=pl.Float64
            )
            .alias("tempat_score"),

            pl.struct([
                "nama_ibu_clean",
                "nama_ibu_master_clean"
            ])
            .map_elements(
                lambda x: (
                    self.scoring_service.safe_jaro(
                        x["nama_ibu_clean"],
                        x["nama_ibu_master_clean"]
                    )
                    if x["nama_ibu_clean"]
                    else None
                ),
                return_dtype=pl.Float64
            )
            .alias("ibu_score"),

            (
                pl.when(
                    pl.col("tanggal_lahir_clean") == ""
                )
                .then(None)

                .when(
                    pl.col("tanggal_lahir_clean")
                    ==
                    pl.col("tanggal_lahir_master_clean")
                )
                .then(1.0)

                .otherwise(0.0)
            )
            .alias("tanggal_score")
        ])

        candidate_df = candidate_df.with_columns([

            (
                (pl.col("tempat_lahir_clean") == "")
                    .cast(pl.Int8)

                +

                (pl.col("tanggal_lahir_clean") == "")
                    .cast(pl.Int8)

                +

                (pl.col("nama_ibu_clean") == "")
                    .cast(pl.Int8)

            ).alias("missing_count")
        ])

        candidate_df = candidate_df.with_columns([

            (
                pl.lit(0.6)

                +

                pl.when(
                    pl.col("tempat_score").is_not_null()
                )
                .then(0.05)
                .otherwise(0)

                +

                pl.when(
                    pl.col("tanggal_score").is_not_null()
                )
                .then(0.3)
                .otherwise(0)

                +

                pl.when(
                    pl.col("ibu_score").is_not_null()
                )
                .then(0.05)
                .otherwise(0)

            ).alias("active_weight")
        ])

        candidate_df = candidate_df.with_columns(
            (
                (
                    (pl.col("nama_score") * 0.6)

                    +

                    (
                        pl.col("tempat_score")
                        .fill_null(0)
                        * 0.05
                    )

                    +

                    (
                        pl.col("tanggal_score")
                        .fill_null(0)
                        * 0.3
                    )

                    +

                    (
                        pl.col("ibu_score")
                        .fill_null(0)
                        * 0.05
                    )
                )

                /

                pl.col("active_weight")
            ).alias("final_score")
        )

        candidate_df = candidate_df.with_columns([

            pl.when(
                pl.col("missing_count") > 2
            )
            .then(pl.lit("AUTO_UNMATCH"))

            .when(
                (
                    pl.col("missing_count") == 1
                )
                &
                (
                    pl.col("final_score") >= 0.9
                )
            )
            .then(pl.lit("AUTO_MATCH"))

            .when(
                (
                    pl.col("missing_count") == 2
                )
                &
                (
                    pl.col("final_score") > 0.85
                )
                &
                (
                    pl.col("final_score") < 0.9
                )
            )
            .then(pl.lit("MANUAL_REVIEW"))

            .when(
                pl.col("final_score") <= 0.85
            )
            .then(pl.lit("AUTO_UNMATCH"))

            .otherwise(
                pl.lit("MANUAL_REVIEW")
            )

            .alias("match_result")
        ])

        #
        # keep best candidate only
        #

        candidate_df = (
            candidate_df
            .sort(
                ["incoming_row_id", "final_score"],
                descending=[False, True]
            )
            .group_by("incoming_row_id")
            .first()
        )

        print(
            f"Best candidates: {candidate_df.height}"
        )

        results = (
            candidate_df
            .select([

                pl.lit(None)
                    .alias("nik_incoming"),

                pl.col("nik_master"),

                pl.lit(file_id)
                    .alias("file_id"),

                (
                    pl.col("final_score") * 100
                )
                .round(2)
                .alias("match_score"),

                pl.col("match_result"),

                pl.lit(
                    uploaded_file[
                        "upload_timestamp"
                    ]
                )
                .alias("upload_date")
            ])
            .to_dicts()
        )

        matching_time_ms = round(
            (time.perf_counter() - start) * 1000,
            2
        )

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

            "message":
                "Grade D matching completed",

            "file_id":
                file_id,

            "processed_rows":
                len(results),

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
                ),

            "matching_time_ms":
                matching_time_ms
        }
