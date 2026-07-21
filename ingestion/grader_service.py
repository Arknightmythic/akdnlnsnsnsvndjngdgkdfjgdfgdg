import time
import polars as pl
from sqlalchemy import text
from datetime import datetime
from .enums import Grade, Process


class GraderService:

    def __init__(self, engine):
        self.engine = engine

    def _grade_dataframe(self, lf: pl.LazyFrame, file_id, minio_path) -> None:
        try:
            target_columns = {"nik", "nama", "tempat_lahir", "tanggal_lahir", "jenis_kelamin", "nama_ibu"}
            lf_columns_set = set(lf.collect_schema().names())
            
            # Build expressions for existing target columns only
            expressions = [pl.len().alias("total_rows")]
            for col in sorted(lf_columns_set & target_columns):
                nonnull_expr = (
                    (pl.len() - pl.col(col).null_count()) / pl.len()
                ).alias(f"{col}_nonnull")
                expressions.append(nonnull_expr)

                null_count_expr = pl.col(col).null_count().alias(f"{col}_null_count")
                expressions.append(null_count_expr)

                if col == "nik":
                    len16_expr = (
                        (pl.col(col).cast(pl.String).str.len_chars() == 16).sum()
                        / pl.len()
                    ).alias("nik_len16")
                    expressions.append(len16_expr)

                    not_len16_count_expr = (
                        (pl.col(col).cast(pl.String).str.len_chars() != 16).sum()
                    ).alias("nik_not_len16_count")
                    expressions.append(not_len16_count_expr)

            if expressions:
                result_df = lf.select(expressions).collect(streaming=True)
                total_rows = result_df["total_rows"][0]
                if total_rows > 0:
                    pcts = {col_name: result_df[col_name][0] for col_name in result_df.columns}
                else:
                    pcts = {}
            else:
                pcts = {}

            # Build results dict with defaults for missing columns
            results: dict = {}
            for col in target_columns:
                exists = col in lf_columns_set
                results[f"{col}_exists"] = exists
                results[f"{col}_nonnull"] = pcts.get(f"{col}_nonnull", 0.0)
                results[f"{col}_null_count"] = pcts.get(f"{col}_null_count", 0)
            results["nik_len16"] = pcts.get("nik_len16", 0.0)
            results["nik_not_len16_count"] = pcts.get("nik_not_len16_count", 0)

            # Grading logic (checked in order: A, B, C, D, E, else F)
            grade = Grade.F.value

            nik_exists = results["nik_exists"]
            b_to_f = ["nama", "tempat_lahir", "tanggal_lahir", "jenis_kelamin", "nama_ibu"]
            b_to_f_exist = all(results[f"{c}_exists"] for c in b_to_f)
            all_6_exist = nik_exists and b_to_f_exist

            # Grade A & B: all 6 columns must exist
            if all_6_exist:
                all_100_nonnull = all(
                    results[f"{c}_null_count"] == 0 for c in target_columns
                )
                len16_100 = results["nik_not_len16_count"] == 0
                if all_100_nonnull and len16_100:
                    grade = Grade.A.value
                elif (
                    results["nik_len16"] >= 0.7
                    and results["nama_null_count"] == 0
                    and results["tempat_lahir_nonnull"] >= 0.7
                    and results["tanggal_lahir_nonnull"] >= 0.7
                    and results["jenis_kelamin_nonnull"] >= 0.7
                    and results["nama_ibu_nonnull"] >= 0.6
                ):
                    grade = Grade.B.value

            # Grade C & D: nik must NOT exist, but nama_lengkap..nama_ibu must all exist
            if grade == Grade.F.value and not nik_exists and b_to_f_exist:
                all_b_to_f_100 = all(
                    results[f"{c}_null_count"] == 0 for c in b_to_f
                )
                if all_b_to_f_100:
                    grade = Grade.C.value
                elif (
                    results["nama_null_count"] == 0
                    and results["tempat_lahir_nonnull"] >= 0.7
                    and results["tanggal_lahir_nonnull"] >= 0.7
                    and results["jenis_kelamin_nonnull"] >= 0.7
                    and results["nama_ibu_nonnull"] >= 0.6
                ):
                    grade = Grade.D.value

            if grade == Grade.F.value:
                hn = results["nama_exists"]
                htl = results["tanggal_lahir_exists"]
                htmp = results["tempat_lahir_exists"]
                
                e1 = hn and htl and results["jenis_kelamin_exists"]
                e2 = hn and htmp and htl
                e3 = hn and htmp and results["nama_ibu_exists"]
                e4 = hn and htl and any(c in lf_columns_set for c in ["provinsi", "kabupaten", "kecamatan", "kelurahan"])
                
                if e1 or e2 or e3 or e4:
                    grade = Grade.E.value

            return grade

        except Exception as e:
            print(f"Failed grading file for {minio_path}: {str(e)}")
            raise

    def grade_file(self, file_id, lf, minio_path):
        try:
            grading_start = time.perf_counter()
            grade = self._grade_dataframe(lf, file_id, minio_path)
            grading_time = int((time.perf_counter() - grading_start) * 1000) # Turn it into ms

            record = {
                "file_id": file_id,
                "grade": int(grade),
                "processing_status": int(Process.GRADED.value),
                # naive local/Jakarta — disamakan dengan metadata_service.py yang
                # INSERT kolom yang sama (lihat BUG_FIXING_GUIDE.md #9)
                "upload_timestamp": datetime.now(),
                "grading_time_ms": grading_time,
            }

            query = text("""
                UPDATE uploaded_files 
                SET 
                    grade = :grade,
                    processing_status = :processing_status,
                    upload_timestamp = :upload_timestamp,
                    grading_time_ms = :grading_time_ms
                WHERE file_id = :file_id
            """)

            with self.engine.begin() as conn:
                conn.execute(query, record)
        except Exception as e:
            print(f"Failed grading file: {minio_path}: {str(e)}")
            raise
