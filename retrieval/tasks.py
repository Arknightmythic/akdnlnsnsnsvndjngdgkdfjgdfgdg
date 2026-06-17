# retrieval/tasks.py
import os
import io
import pandas as pd
import asyncio
from celery import Task
from sqlalchemy import create_engine
from minio import Minio
from worker import celery_app

from retrieval.repository import RetrieveRepository
from util.parquet_loader import ParquetLoader

def _make_engine():
    return create_engine(
        f"mysql+pymysql://{os.getenv('STARROCKS_USER')}:{os.getenv('STARROCKS_PASSWORD')}"
        f"@{os.getenv('STARROCKS_HOST')}:{os.getenv('STARROCKS_PORT')}/{os.getenv('STARROCKS_DATABASE')}",
        pool_pre_ping=True, pool_recycle=1800, pool_size=2,
    )

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
                secure=False
            )
        return self._minio_client

@celery_app.task(bind=True, base=ExportTask, name="retrieval.generate_export_csv", acks_late=True)
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
        parquet_loader = ParquetLoader(self.minio_client, bucket_name)
        parquet_map = asyncio.run(parquet_loader.load_rows(file_id, meta["minio_path"], incoming_ids))

        # 3. Ambil data Master (StarRocks)
        master_map = repo.get_master_by_niks(master_niks)

        # 4. Konstruksi Data Match (Dinamis)
        match_list = []
        for r in match_rows:
            # inc akan mengambil seluruh field bawaan asli parquet secara otomatis
            inc = parquet_map.get(str(r["id_incoming"]), {}).copy()
            inc.pop("id", None) # Hapus kolom id internal bawaan parquet jika ada
            
            # Kita gabungkan data mentah parquet dengan data master sebagai sandingan
            mst = master_map.get(r["nik_master"], {})
            row_data = {**inc}
            
            for k, v in mst.items():
                row_data[f"master_{k}"] = v
                
            match_list.append(row_data)

        # 5. Konstruksi Data Unmatch (Dinamis)
        unmatch_list = []
        for r in unmatch_rows:
            inc = parquet_map.get(str(r["id_incoming"]), {}).copy()
            inc.pop("id", None)
            
            unmatch_list.append(inc)

        # 6. Konversi ke CSV & Upload ke MinIO
        match_path = f"download/{file_id}/match.csv"
        unmatch_path = f"download/{file_id}/unmatch.csv"

        # Menggunakan sep=';' agar kolom langsung otomatis terpisah dengan rapi saat dibuka
        df_match = pd.DataFrame(match_list)
        csv_match = df_match.to_csv(index=False, sep=';').encode('utf-8')
        self.minio_client.put_object(bucket_name, match_path, io.BytesIO(csv_match), len(csv_match))

        df_unmatch = pd.DataFrame(unmatch_list)
        csv_unmatch = df_unmatch.to_csv(index=False, sep=';').encode('utf-8')
        self.minio_client.put_object(bucket_name, unmatch_path, io.BytesIO(csv_unmatch), len(csv_unmatch))

        # 7. Update status ke READY
        repo.update_export_status(file_id, "READY", match_path, unmatch_path)
        return {"status": "SUCCESS", "file_id": file_id}
        
    except Exception as e:
        repo.update_export_status(file_id, "FAILED")
        raise self.retry(exc=e, max_retries=3, countdown=30)