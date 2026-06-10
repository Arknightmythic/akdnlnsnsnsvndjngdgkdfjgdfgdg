import pyarrow.dataset as ds
import s3fs
import os
import math

class ParquetLoader:

    def __init__(self, minio_client, bucket):
        self.minio = minio_client
        self.bucket = bucket
        self.fs = s3fs.S3FileSystem(
            key=os.getenv("MINIO_ACCESS_KEY"),
            secret=os.getenv("MINIO_SECRET_KEY"),
            endpoint_url=f"http://{os.getenv('MINIO_ENDPOINT')}"
        )

    @staticmethod
    def _sanitize(value):
        """Replace non-JSON-compliant floats with None."""
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value

    def load_rows(self, minio_path: str, incoming_ids: list):
        dataset = ds.dataset(
            f"{self.bucket}/{minio_path}",
            filesystem=self.fs,
            format="parquet"
        )

        table = dataset.to_table(
            filter=ds.field("id").isin([str(x) for x in incoming_ids])
        )
        df = table.to_pandas()

        return {
            str(row["id"]): {k: self._sanitize(v) for k, v in row.to_dict().items()}
            for _, row in df.iterrows()
        }