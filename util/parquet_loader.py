import pyarrow.dataset as ds
import s3fs
import os
import math, json

class ParquetLoader:
    """
    Loads row-level data from Parquet files stored in MinIO and applies
    Redis caching to reduce repeated Parquet scans and MinIO access.
    """
    def __init__(self, minio_client, bucket, redis=None):
        """
        Initialize MinIO, filesystem, and optional Redis dependencies used
        for Parquet access and row-level caching.
        """
        self.minio = minio_client
        self.bucket = bucket
        self.fs = s3fs.S3FileSystem(
            key=os.getenv("MINIO_ACCESS_KEY"),
            secret=os.getenv("MINIO_SECRET_KEY"),
            endpoint_url=f"http://{os.getenv('MINIO_ENDPOINT')}"
        )
        self.redis = redis

    @staticmethod
    def _sanitize(value):
        """
        Convert unsupported JSON values (NaN, Infinity, -Infinity) to None
        before serializing data for API responses or Redis storage.
        """
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value    

    async def load_rows(self, file_id, minio_path, incoming_ids):
        """
        Retrieve requested rows from Redis cache when available. For cache
        misses, read matching rows from the Parquet file, cache the results,
        and return a consolidated row mapping keyed by row ID.
        """
        result = {}
        missing_ids = []

        for incoming_id in incoming_ids:

            cache_key = (f"parquet:{file_id}:{incoming_id}")

            cached = None

            if self.redis:
                cached = await self.redis.get(cache_key)

            if cached:
                result[str(incoming_id)] = (json.loads(cached))

            else:
                missing_ids.append(incoming_id)

        if not missing_ids:
            return result

        dataset = ds.dataset(
                f"{self.bucket}/{minio_path}",
                filesystem=self.fs,
                format="parquet"
            )

        id_type = dataset.schema.field("id").type

        if str(id_type).startswith(("int", "uint")):
            ids = [int(x) for x in missing_ids]
        else:
            ids = [str(x) for x in missing_ids]

        table = dataset.to_table(filter=ds.field("id").isin(ids))

        rows = table.to_pylist()

        for row in rows:
            row_data = {
                k: self._sanitize(v)
                for k, v in row.items()
            }

            row_id = str(row["id"])
            result[row_id] = row_data

            if self.redis:
                await self.redis.set(
                    f"parquet:{file_id}:{row_id}",
                    json.dumps(
                        row_data,
                        default=str
                    ),
                    ex=604800
                )

        return result