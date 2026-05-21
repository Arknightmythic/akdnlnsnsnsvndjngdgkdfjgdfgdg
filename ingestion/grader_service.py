from sqlalchemy import text
from datetime import datetime, timezone
from util.timer import record_time
import polars as pl


class GraderService:

    def __init__(self, engine):
        self.engine = engine

    @record_time
    def _grade_dataframe(self, lf: pl.LazyFrame, file_id, minio_path) -> None:
        try:
            target_columns = {"nik", "nama", "tempat_lahir", "tanggal_lahir", "jenis_kelamin", "nama_ibu"}

            lf_columns_set = set(lf.columns)
            total_rows = lf.select(pl.len()).collect().item()

            # Build expressions for existing target columns only
            expressions = []
            for col in sorted(lf_columns_set & target_columns):
                nonnull_expr = (
                    (pl.lit(total_rows) - pl.col(col).null_count()) / pl.lit(total_rows)
                ).alias(f"{col}_nonnull")
                expressions.append(nonnull_expr)

                if col == "nik":
                    len16_expr = (
                        (pl.col(col).cast(pl.String).str.len_chars() == 16).sum() / pl.lit(total_rows)
                    ).alias("nik_len16")
                    expressions.append(len16_expr)

            if total_rows > 0 and expressions:
                result_df = lf.select(expressions).collect()
                pcts = {col_name: result_df[col_name][0] for col_name in result_df.columns}
            else:
                pcts = {}

            # Build results dict with defaults for missing columns
            results: dict = {}
            for col in target_columns:
                exists = col in lf_columns_set
                results[f"{col}_exists"] = exists
                results[f"{col}_nonnull"] = pcts.get(f"{col}_nonnull", 0.0)
            results["nik_len16"] = pcts.get("nik_len16", 0.0)

            # --- Grading logic (checked in order: A, B, C, D, else E) ---
            grade = "E"

            nik_exists = results["nik_exists"]
            b_to_f = ["nama", "tempat_lahir", "tanggal_lahir", "jenis_kelamin", "nama_ibu"]
            b_to_f_exist = all(results[f"{c}_exists"] for c in b_to_f)
            all_6_exist = nik_exists and b_to_f_exist

            # Grade A & B: all 6 columns must exist
            if all_6_exist:
                all_100_nonnull = all(
                    results[f"{c}_nonnull"] >= 0.9999 for c in target_columns
                )
                len16_100 = results["nik_len16"] >= 0.9999
                if all_100_nonnull and len16_100:
                    grade = "A"
                elif (
                    results["nik_len16"] >= 0.7
                    and results["nama_nonnull"] >= 0.9999
                    and results["tempat_lahir_nonnull"] >= 0.7
                    and results["tanggal_lahir_nonnull"] >= 0.7
                    and results["jenis_kelamin_nonnull"] >= 0.7
                    and results["nama_ibu_nonnull"] >= 0.6
                ):
                    grade = "B"

            # Grade C & D: nik must NOT exist, but nama_lengkap..nama_ibu must all exist
            if grade == "E" and not nik_exists and b_to_f_exist:
                all_b_to_f_100 = all(
                    results[f"{c}_nonnull"] >= 0.9999 for c in b_to_f
                )
                if all_b_to_f_100:
                    grade = "C"
                elif (
                    results["nama_nonnull"] >= 0.9999
                    and results["tempat_lahir_nonnull"] >= 0.7
                    and results["tanggal_lahir_nonnull"] >= 0.7
                    and results["jenis_kelamin_nonnull"] >= 0.7
                    and results["nama_ibu_nonnull"] >= 0.6
                ):
                    grade = "D"

            record = {
                "file_id": file_id,
                "upload_timestamp": datetime.now(timezone.utc),
                "processing_status": "GRADED",
                "grade": grade,
            }

            insert_query = text("""
                UPDATE uploaded_files 
                SET 
                    grade = :grade,
                    processing_status = :processing_status,
                    upload_timestamp = :upload_timestamp
                WHERE file_id = :file_id
            """)

            with self.engine.begin() as conn:
                conn.execute(insert_query, record)

        except Exception as e:
            print(f"Failed grading file for {minio_path}: {str(e)}")
            raise

    def grade_file(self, file_id, file_to_be_graded, minio_path):
        try:
            lf = pl.scan_csv(file_to_be_graded)
            self._grade_dataframe(lf, file_id, minio_path)

        except Exception as e:
            print(f"Failed grading file: {minio_path}: {str(e)}")
            raise