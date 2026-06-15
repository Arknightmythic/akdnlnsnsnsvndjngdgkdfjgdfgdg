from .repository import RetrieveRepository
from util.parquet_loader import ParquetLoader
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
import json

class RetrieveDataHandler:
    PAGE_SIZE_GRADED = 10
    PAGE_SIZE_MANUAL_DATA = 10
    PAGE_SIZE_SYNCHRONIZED = 15

    def __init__(self, engine, parquet_loader = None, redis=None):
        self.repository = RetrieveRepository(engine)
        self.parquet_loader = parquet_loader
        self.redis = redis

    def get_graded_files(self, page):
        """
        Retrieve a paginated list of graded files..
        """
        data, total_rows = self.repository.get_graded_files(
            page=page,
            page_size=self.PAGE_SIZE_GRADED
        )

        total_pages = (total_rows + self.PAGE_SIZE_GRADED - 1) // self.PAGE_SIZE_GRADED

        return {
            "page": page,
            "page_size": self.PAGE_SIZE_GRADED,
            "total_rows": total_rows,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
            "data": data
        }
    

    def get_synchronized_files(
        self,
        page,
        institution_name,
        grade,
        sync_status
    ):
        """
        Retrieve a paginated list of synchronized files with optional filtering
        by institution, grade, and synchronization status.
        """
        data, total_rows = self.repository.get_synchronized_files(
            page=page,
            page_size=self.PAGE_SIZE_SYNCHRONIZED,
            institution_name=institution_name,
            grade=grade,
            sync_status=sync_status
        )

        total_pages = (
            total_rows + self.PAGE_SIZE_SYNCHRONIZED - 1
        ) // self.PAGE_SIZE_SYNCHRONIZED

        return {
            "page": page,
            "page_size": self.PAGE_SIZE_SYNCHRONIZED,
            "total_rows": total_rows,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "data": data
        }
    
    def get_history_data(
        self,
        page,
        institution_name,
        start_date,
        end_date
    ):
        data, total_rows = self.repository.get_history_data(
            page=page,
            page_size=self.PAGE_SIZE_SYNCHRONIZED,
            institution_name=institution_name,
            start_date=start_date,
            end_date=end_date
        )

        for row in data:
            total_records = (
                row["total_auto_match"]
                + row["total_manual_match"]
                + row["total_unmatch"]
            )

            row["percentage_unmatch"] = (
                round((row["total_unmatch"] / total_records) * 100, 2)
                if total_records > 0
                else 0
            )

        total_pages = (
            total_rows + self.PAGE_SIZE_SYNCHRONIZED - 1
        ) // self.PAGE_SIZE_SYNCHRONIZED

        return {
            "page": page,
            "page_size": self.PAGE_SIZE_SYNCHRONIZED,
            "total_rows": total_rows,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "data": data
        }
    
    async def get_preview_data(self, file_id):
        """
        Build and cache the preview dataset for a completed synchronization file.
        """

        cache_key = f"preview:{file_id}"

        cached = await self.redis.get(cache_key)

        if cached:
            print(f"[CACHE HIT] {file_id}")
            return json.loads(cached)
    
        print(f"[CACHE MISS] {file_id}")

        meta = self.repository.get_minio_path(file_id)
        if not meta:
            raise HTTPException(
                status_code=404,
                detail="File not found"
            )

        if meta["is_sync"] != 1 and meta["sync_status"] != 3:
            raise HTTPException(
                status_code=409,
                detail="File has not been synchronized or completed yet"
            )

        minio_path = meta["minio_path"]

        rows = self.repository.get_completed_data(file_id)

        match_rows = rows["match"]
        unmatch_rows = rows["unmatch"]

        incoming_ids = []
        master_niks = []

        for row in match_rows:
            incoming_ids.append(
                str(row["id_incoming"])
            )

            if row["nik_master"]:
                master_niks.append(
                    row["nik_master"]
                )

        for row in unmatch_rows:
            incoming_ids.append(
                str(row["id_incoming"])
            )

        parquet_map = await self.parquet_loader.load_rows(
            file_id,
            minio_path,
            incoming_ids
        )

        master_map = (
            self.repository.get_master_by_niks(
                master_niks
            )
        )

        match_result = []

        for row in match_rows:

            institution = parquet_map.get(
                str(row["id_incoming"]),
                {}
            ).copy()

            institution.update({
                "match_score": row["match_score"],
                "match_result_desc":
                    row["match_result_name"],
                "file_id": row["file_id"]
            })

            match_result.append({
                "institution": institution,
                "master": master_map.get(
                    row["nik_master"]
                )
            })

        unmatch_result = []

        for row in unmatch_rows:

            institution = parquet_map.get(
                str(row["id_incoming"]),
                {}
            ).copy()

            institution.update({
                "match_score": row["match_score"],
                "match_result_desc":
                    row["match_result_name"],
                "file_id": row["file_id"]
            })

            unmatch_result.append({
                "institution": institution
            })

        result = {
            "data": {
                "match": match_result,
                "unmatch": unmatch_result
            }
        }

        cache_value = jsonable_encoder(result)
        await self.redis.set(
            cache_key,
            json.dumps(cache_value),
            ex=604800  # 7 hari
        )

        return result
    
    async def get_master_by_niks_cached(self, niks):
        """
        Fetch master data for the provided NIKs, returning cached records when
        available and loading missing records from the repository as needed.
        """
        if not niks:
            return {}

        result = {}
        missing_niks = []

        for nik in niks:
            cache_key = f"master:{nik}"

            cached = await self.redis.get(cache_key)

            if cached:
                result[nik] = json.loads(cached)
            else:
                missing_niks.append(nik)

        if missing_niks:
            db_result = (
                self.repository.get_master_by_niks(
                    missing_niks
                )
            )

            for nik, data in db_result.items():
                result[nik] = data

                await self.redis.set(
                    f"master:{nik}",
                    json.dumps(
                        jsonable_encoder(data)
                    ),
                    ex=2592000  # 30 hari
                )

        return result
    
    async def get_manual_review_data(self, file_id, page):
        """
        Prepare paginated manual review data from
        cached Parquet records, and related master records into a unified response.
        """
        meta = self.repository.get_minio_path(file_id)
        if not meta:
            raise HTTPException(
                status_code=404,
                detail="File not found"
            )

        if meta["is_sync"] != 1 and meta["sync_status"] != 2:
            raise HTTPException(
                status_code=409,
                detail="File has not been completely synchronized yet or do not need manual review."
            )

        minio_path = meta["minio_path"]

        manual_rows, total_rows = self.repository.get_manual_review_data(file_id, page, page_size=self.PAGE_SIZE_MANUAL_DATA)

        incoming_ids = []
        master_niks = []

        for row in manual_rows:
            incoming_ids.append(
                str(row["id_incoming"])
            )

            if row["nik_master"]:
                master_niks.append(
                    row["nik_master"]
                )

        parquet_map = await self.parquet_loader.load_rows(
            file_id,
            minio_path,
            incoming_ids
        )

        master_map = (
            await self.get_master_by_niks_cached(
                master_niks
            )
        )

        manual_result = []

        for row in manual_rows:

            institution = parquet_map.get(
                str(row["id_incoming"]),
                {}
            ).copy()

            institution.update({
                "match_score": row["match_score"],
                "match_result_desc": row["match_result_name"],
                "file_id": row["file_id"],
                "reason": row["reason"]
            })

            manual_result.append({
                "institution": institution,
                "master": master_map.get(
                    row["nik_master"]
                )
            })

        total_pages = (
            total_rows + self.PAGE_SIZE_SYNCHRONIZED - 1
        ) // self.PAGE_SIZE_SYNCHRONIZED

        return {
            "page": page,
            "page_size": self.PAGE_SIZE_GRADED,
            "total_rows": total_rows,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
            "data": manual_result
        }