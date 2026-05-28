import time
from pathlib import Path

import polars as pl

TARGET_COLUMNS = {"nik", "nama", "tempat_lahir", "tanggal_lahir", "jenis_kelamin", "nama_ibu"}


def grade_lazyframe(lf: pl.LazyFrame) -> str:
    """
    Core grading logic copied from GraderService._grade_dataframe.
    Computes column existence, non-null percentages, NIK length checks,
    and assigns a grade (A-E). DB write operations are stripped out.
    """
    target_columns = {"nik", "nama", "tempat_lahir", "tanggal_lahir", "jenis_kelamin", "nama_ibu"}
    lf_columns_set = set(lf.columns)

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

    # --- Grading logic (checked in order: A, B, C, D, else E) ---
    grade = "E"

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
            grade = "A"
        elif (
            results["nik_len16"] >= 0.7
            and results["nama_null_count"] == 0
            and results["tempat_lahir_nonnull"] >= 0.7
            and results["tanggal_lahir_nonnull"] >= 0.7
            and results["jenis_kelamin_nonnull"] >= 0.7
            and results["nama_ibu_nonnull"] >= 0.6
        ):
            grade = "B"

    # Grade C & D: nik must NOT exist, but nama_lengkap..nama_ibu must all exist
    if grade == "E" and not nik_exists and b_to_f_exist:
        all_b_to_f_100 = all(
            results[f"{c}_null_count"] == 0 for c in b_to_f
        )
        if all_b_to_f_100:
            grade = "C"
        elif (
            results["nama_null_count"] == 0
            and results["tempat_lahir_nonnull"] >= 0.7
            and results["tanggal_lahir_nonnull"] >= 0.7
            and results["jenis_kelamin_nonnull"] >= 0.7
            and results["nama_ibu_nonnull"] >= 0.6
        ):
            grade = "D"

    return grade


def main():
    data_dir = Path("data")
    csv_files = sorted(data_dir.glob("*.csv"))
    multipliers = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512]
    # multipliers = [4096] # 4096 * 200,000 = 819,200,000 rows

    results = []

    for csv_path in csv_files:
        csv_name = csv_path.stem
        print(f"Processing {csv_name}...")

        for multiplier in multipliers:
            # --- Step A: CSV read and convert to LazyFrame (copied from handler.py logic) ---
            conv_start = time.perf_counter()
            lf = pl.scan_csv(str(csv_path))
            conv_time = (time.perf_counter() - conv_start) * 1000

            # --- Multiply rows by appending the data to itself ---
            if multiplier > 1:
                df = lf.collect()
                df_multiplied = pl.concat([df] * multiplier)
                lf = df_multiplied.lazy()

            # --- Step B: Grade the LazyFrame (copied from grader_service.py logic) ---
            grade_start = time.perf_counter()
            assigned_grade = grade_lazyframe(lf)
            grade_time = (time.perf_counter() - grade_start) * 1000

            results.append(
                {
                    "csv_name": csv_name,
                    "row_multiplier": multiplier,
                    "conversion_time": round(conv_time, 6),
                    "grading_time": round(grade_time, 6),
                }
            )

            row_count = 200_000 * multiplier
            print(
                f"  x{multiplier:>2} ({row_count:>9,} rows)  "
                f"conv: {conv_time:.4f}ms  grade: {grade_time:.4f}ms  grade: {assigned_grade}"
            )

    result_df = pl.DataFrame(results)
    print("\n" + "=" * 100)
    print("GRADING TIME PERFORMANCE RESULTS")
    print("=" * 100)
    print(result_df)


if __name__ == "__main__":
    main()