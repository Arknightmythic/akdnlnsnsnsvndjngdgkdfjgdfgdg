from .repository import RetrieveRepository
from util.parquet_loader import ParquetLoader
from fastapi import HTTPException

class RetrieveDataHandler:
    PAGE_SIZE_GRADED = 10
    PAGE_SIZE_SYNCHRONIZED = 15

    def __init__(self, engine, parquet_loader = None):
        self.repository = RetrieveRepository(engine)
        self.parquet_loader = parquet_loader

    def get_graded_files(self, page):
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
    
    def get_preview_data(self, file_id):

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

        parquet_map = self.parquet_loader.load_rows(
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

        return {
        "data": {
            "match": match_result,
            "unmatch": unmatch_result
        }
        
    }
