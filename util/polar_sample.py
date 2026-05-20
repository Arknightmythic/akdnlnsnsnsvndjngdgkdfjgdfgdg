from minio import Minio
from minio.error import S3Error
import polars as pl
from rapidfuzz.distance import JaroWinkler
from io import BytesIO

# =========================================
# CONFIG
# =========================================

MINIO_ENDPOINT = "localhost:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"

RAW_BUCKET = "raw"
CURATED_BUCKET = "curated"

MASTER_OBJECT = "master_data.csv"
INCOMING_OBJECT = "incoming_data.csv"

# =========================================
# CONNECT TO MINIO
# =========================================

client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

# =========================================
# CREATE BUCKETS IF NOT EXISTS
# =========================================

for bucket in [RAW_BUCKET, CURATED_BUCKET]:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        print(f"Created bucket: {bucket}")

# =========================================
# READ FILES FROM MINIO
# =========================================

def read_csv_from_minio(bucket_name, object_name):
    response = client.get_object(bucket_name, object_name)

    try:
        data = response.read()
        return pl.read_csv(BytesIO(data))

    finally:
        response.close()
        response.release_conn()

master_df = read_csv_from_minio(
    RAW_BUCKET,
    MASTER_OBJECT
)

incoming_df = read_csv_from_minio(
    RAW_BUCKET,
    INCOMING_OBJECT
)

print("Master rows :", master_df.height)
print("Incoming rows:", incoming_df.height)

# =========================================
# ETL STEP 1 - CLEANING
# =========================================

incoming_df = (
    incoming_df
    .with_columns([
        pl.col("customer_name")
            .fill_null("UNKNOWN"),

        pl.col("merchant_name")
            .str.to_uppercase(),

        pl.col("status")
            .str.to_uppercase(),

        pl.col("amount")
            .fill_null(0)
    ])
)

master_df = (
    master_df
    .with_columns([
        pl.col("merchant_name")
            .str.to_uppercase()
    ])
)

# =========================================
# ETL STEP 2 - JOIN
# =========================================

joined_df = incoming_df.join(
    master_df.select([
        "transaction_id",
        "merchant_name"
    ]).rename({
        "merchant_name": "master_merchant_name"
    }),
    on="transaction_id",
    how="left"
)

# =========================================
# ETL STEP 3 - FUZZY MATCH SCORE
# =========================================

def calculate_similarity(row):
    incoming_name = row["merchant_name"]
    master_name = row["master_merchant_name"]

    if incoming_name is None or master_name is None:
        return 0

    return round(
        JaroWinkler.similarity(
            incoming_name,
            master_name
        ),
        4
    )

joined_df = joined_df.with_columns([
    pl.struct([
        "merchant_name",
        "master_merchant_name"
    ])
    .map_elements(calculate_similarity)
    .alias("match_score")
])

# =========================================
# ETL STEP 4 - GRADING
# =========================================

joined_df = joined_df.with_columns([
    pl.when(pl.col("match_score") >= 0.98)
        .then(pl.lit("A"))

    .when(pl.col("match_score") >= 0.90)
        .then(pl.lit("B"))

    .when(pl.col("match_score") >= 0.75)
        .then(pl.lit("C"))

    .otherwise(pl.lit("D"))
    .alias("grade")
])

# =========================================
# ETL STEP 5 - METADATA
# =========================================

metadata = {
    "total_rows": joined_df.height,
    "grade_a": joined_df.filter(pl.col("grade") == "A").height,
    "grade_b": joined_df.filter(pl.col("grade") == "B").height,
    "grade_c": joined_df.filter(pl.col("grade") == "C").height,
    "grade_d": joined_df.filter(pl.col("grade") == "D").height,
}

print("\nMetadata:")
print(metadata)

# =========================================
# WRITE RESULT TO PARQUET
# =========================================

output_file = "processed_transactions.parquet"

joined_df.write_parquet(
    output_file,
    compression="zstd"
)

# =========================================
# UPLOAD RESULT TO MINIO
# =========================================

client.fput_object(
    CURATED_BUCKET,
    "processed/processed_transactions.parquet",
    output_file
)

print("\nUploaded parquet to MinIO")

# =========================================
# SAMPLE OUTPUT
# =========================================

print("\nSample processed data:")
print(
    joined_df.select([
        "transaction_id",
        "merchant_name",
        "master_merchant_name",
        "match_score",
        "grade"
    ]).head(10)
)