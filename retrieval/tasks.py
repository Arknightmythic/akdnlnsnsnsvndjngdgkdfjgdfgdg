import os
import io
import json
import asyncio
import pandas as pd
from celery import Task
from sqlalchemy import create_engine, text
from sqlalchemy import create_engine, text
from minio import Minio
from redis import Redis as SyncRedis
from urllib.parse import urlparse

from redis import Redis as SyncRedis
from urllib.parse import urlparse

from worker import celery_app
from retrieval.repository import RetrieveRepository
from util.parquet_loader import ParquetLoader



def _make_engine():
    return create_engine(
        f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}"
        f"@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}",
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=2,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=2,
    )


# FIX #2: Parse dari REDIS_URL, bukan host/port/db terpisah yang tidak ada di .env
def _make_sync_redis() -> SyncRedis:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    parsed = urlparse(redis_url)
    return SyncRedis(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        db=int(parsed.path.lstrip("/") or 0),
        password=parsed.password or None,
        decode_responses=True,
    )


# FIX #8: Helper untuk menjalankan coroutine secara aman di dalam Celery worker.
# asyncio.run() membuat event loop baru setiap kali — aman di Celery solo/prefork,
# tapi di gevent/eventlet bisa konflik dengan loop yang sudah ada.
# Pendekatan ini lebih defensive: cek dulu apakah sudah ada loop yang running.
def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Gevent/eventlet context — buat loop baru di thread baru
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        # Tidak ada event loop di thread ini — buat yang baru
        return asyncio.run(coro)


class ExportTask(Task):
    _engine = None
    _minio_client = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = _make_engine()
        return self._engine

    @property
    def minio_client(self):
        if self._minio_client is None:
            self._minio_client = Minio(
                os.getenv("MINIO_ENDPOINT"),
                access_key=os.getenv("MINIO_ACCESS_KEY"),
                secret_key=os.getenv("MINIO_SECRET_KEY"),
                secure=False,
            )
        return self._minio_client


@celery_app.task(
    bind=True,
    base=ExportTask,
    name="retrieval.generate_export_csv",
    acks_late=True,
)
def generate_export_csv(self, file_id: str):
    try:
        repo = RetrieveRepository(self.engine)
        repo.update_export_status(file_id, "PROCESSING")

        meta = repo.get_minio_path(file_id)
        if not meta:
            raise Exception("File meta not found")

        bucket_name = os.getenv("RAW_BUCKET_NAME")

        # 1. Ambil data dari StarRocks
        export_data = repo.get_all_export_data(file_id)
        match_rows = export_data["match"]
        unmatch_rows = export_data["unmatch"]

        incoming_ids = [str(r["id_incoming"]) for r in match_rows + unmatch_rows]
        master_niks = [r["nik_master"] for r in match_rows if r["nik_master"]]

        # 2. Ambil data dari Parquet (MinIO)
        # FIX #8: ganti asyncio.run() dengan _run_async() yang aman di semua pool mode
        parquet_loader = ParquetLoader(self.minio_client, bucket_name)
        parquet_map = _run_async(
            parquet_loader.load_rows(file_id, meta["minio_path"], incoming_ids)
        )

        # 3. Ambil data Master (StarRocks)
        master_map = repo.get_master_by_niks(master_niks)

        # 4. Konstruksi Data Match (dinamis)
        match_list = []
        for r in match_rows:
            inc = parquet_map.get(str(r["id_incoming"]), {}).copy()
            inc.pop("id", None)
            mst = master_map.get(r["nik_master"], {})
            row_data = {**inc}
            for k, v in mst.items():
                row_data[f"master_{k}"] = v
            match_list.append(row_data)

        # 5. Konstruksi Data Unmatch (dinamis)
        unmatch_list = []
        for r in unmatch_rows:
            inc = parquet_map.get(str(r["id_incoming"]), {}).copy()
            inc.pop("id", None)
            unmatch_list.append(inc)

        
        match_path = f"download/{file_id}/match.csv"
        unmatch_path = f"download/{file_id}/unmatch.csv"

        df_match = pd.DataFrame(match_list)
        csv_match = df_match.to_csv(index=False, sep=";").encode("utf-8")
        self.minio_client.put_object(
            bucket_name, match_path, io.BytesIO(csv_match), len(csv_match)
        )
        csv_match = df_match.to_csv(index=False, sep=";").encode("utf-8")
        self.minio_client.put_object(
            bucket_name, match_path, io.BytesIO(csv_match), len(csv_match)
        )

        df_unmatch = pd.DataFrame(unmatch_list)
        csv_unmatch = df_unmatch.to_csv(index=False, sep=";").encode("utf-8")
        self.minio_client.put_object(
            bucket_name, unmatch_path, io.BytesIO(csv_unmatch), len(csv_unmatch)
        )
        csv_unmatch = df_unmatch.to_csv(index=False, sep=";").encode("utf-8")
        self.minio_client.put_object(
            bucket_name, unmatch_path, io.BytesIO(csv_unmatch), len(csv_unmatch)
        )

        
        repo.update_export_status(file_id, "READY", match_path, unmatch_path)
        return {"status": "SUCCESS", "file_id": file_id}

    except Exception as e:
        repo.update_export_status(file_id, "FAILED")
        raise self.retry(exc=e, max_retries=3, countdown=30)


@celery_app.task(name="retrieval.flush_access_logs", queue="audit_queue")
def flush_access_logs_to_starrocks():
    # FIX #2: Gunakan _make_sync_redis() yang parse dari REDIS_URL,
    # bukan hardcode host/port/db yang sebelumnya selalu jatuh ke localhost:6379
    redis_client = _make_sync_redis()
    engine = _make_engine()

    logs = []
    # Tarik log dari Redis, batas maksimum 500 log sekali batching
    for _ in range(500):
        item = redis_client.lpop("audit_access_logs")
        if not item:
            break
        logs.append(json.loads(item))

    if not logs:
        return {"flushed": 0}

    query = text("""
        INSERT INTO access_event (
            actor_user_id, action, resource_type, resource_id,
            ip_address, result, latency_ms
        ) VALUES (
            :actor_user_id, :action, :resource_type, :resource_id,
            :ip_address, :result, :latency_ms
        )
    """)

    try:
        with engine.begin() as conn:
            conn.execute(query, logs)
        return {"flushed": len(logs)}
    except Exception as e:
        # Kembalikan log ke Redis agar tidak hilang jika DB gagal
        for log in reversed(logs):
            redis_client.lpush("audit_access_logs", json.dumps(log))
        raise e