from .repository import RetrieveRepository
from util.parquet_loader import ParquetLoader
from audit.audit_service import AuditService
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
import json
from .enum import MatchStatus
from retrieval.tasks import generate_export_csv
from datetime import datetime, timedelta
import zoneinfo

from sqlalchemy import text


class RetrieveDataHandler:
    PAGE_SIZE_GRADED       = 10
    PAGE_SIZE_MANUAL_DATA  = 10
    PAGE_SIZE_SYNCHRONIZED = 15

    def __init__(self, engine, parquet_loader=None, redis=None, minio_client=None, bucket_name=None):
        self.repository     = RetrieveRepository(engine)
        self.parquet_loader = parquet_loader
        self.redis          = redis
        self.minio_client   = minio_client
        self.bucket_name    = bucket_name
        self._audit         = AuditService(engine)

    def get_graded_files(self, page):
        data, total_rows = self.repository.get_graded_files(
            page=page, page_size=self.PAGE_SIZE_GRADED
        )
        total_pages = (total_rows + self.PAGE_SIZE_GRADED - 1) // self.PAGE_SIZE_GRADED
        return {
            "page": page, "page_size": self.PAGE_SIZE_GRADED,
            "total_rows": total_rows, "total_pages": total_pages,
            "has_next": page < total_pages, "has_prev": page > 1,
            "data": data,
        }

    def get_synchronized_files(self, page, institution_name, grade, sync_status):
        data, total_rows = self.repository.get_synchronized_files(
            page=page, page_size=self.PAGE_SIZE_SYNCHRONIZED,
            institution_name=institution_name, grade=grade, sync_status=sync_status,
        )
        total_pages = (total_rows + self.PAGE_SIZE_SYNCHRONIZED - 1) // self.PAGE_SIZE_SYNCHRONIZED
        return {
            "page": page, "page_size": self.PAGE_SIZE_SYNCHRONIZED,
            "total_rows": total_rows, "total_pages": total_pages,
            "has_prev": page > 1, "has_next": page < total_pages,
            "data": data,
        }

    def get_history_data(self, page, institution_name, start_date, end_date):
        data, total_rows = self.repository.get_history_data(
            page=page, page_size=self.PAGE_SIZE_SYNCHRONIZED,
            institution_name=institution_name, start_date=start_date, end_date=end_date,
        )
        for row in data:
            total_records = (
                row["total_auto_match"] + row["total_manual_match"] + row["total_unmatch"]
            )
            row["percentage_unmatch"] = (
                round((row["total_unmatch"] / total_records) * 100, 2) if total_records > 0 else 0
            )
        total_pages = (total_rows + self.PAGE_SIZE_SYNCHRONIZED - 1) // self.PAGE_SIZE_SYNCHRONIZED
        return {
            "page": page, "page_size": self.PAGE_SIZE_SYNCHRONIZED,
            "total_rows": total_rows, "total_pages": total_pages,
            "has_prev": page > 1, "has_next": page < total_pages,
            "data": data,
        }

    async def get_preview_data(self, file_id):
        cache_key = f"preview:{file_id}"
        cached = await self.redis.get(cache_key)
        if cached:
            print(f"[CACHE HIT] {file_id}")
            return json.loads(cached)

        print(f"[CACHE MISS] {file_id}")
        meta = self.repository.get_minio_path(file_id)
        if not meta:
            raise HTTPException(status_code=404, detail="File not found")
        if meta["is_sync"] != 1 and meta["sync_status"] != 3:
            raise HTTPException(status_code=409, detail="File has not been synchronized or completed yet")

        rows        = self.repository.get_completed_data(file_id)
        match_rows  = rows["match"]
        unmatch_rows = rows["unmatch"]

        incoming_ids = [str(r["id_incoming"]) for r in match_rows + unmatch_rows]
        master_niks  = [r["nik_master"] for r in match_rows if r["nik_master"]]

        parquet_map = await self.parquet_loader.load_rows(file_id, meta["minio_path"], incoming_ids)
        master_map  = self.repository.get_master_by_niks(master_niks)

        match_result = []
        for row in match_rows:
            institution = parquet_map.get(str(row["id_incoming"]), {}).copy()
            institution.update({
                "match_score": row["match_score"],
                "match_result_desc": row["match_result_name"],
                "file_id": row["file_id"],
            })
            match_result.append({"institution": institution, "master": master_map.get(row["nik_master"])})

        unmatch_result = []
        for row in unmatch_rows:
            institution = parquet_map.get(str(row["id_incoming"]), {}).copy()
            institution.update({
                "match_score": row["match_score"],
                "match_result_desc": row["match_result_name"],
                "file_id": row["file_id"],
            })
            unmatch_result.append({"institution": institution})

        result = {"data": {"match": match_result, "unmatch": unmatch_result}}
        cache_value = jsonable_encoder(result)
        await self.redis.set(cache_key, json.dumps(cache_value), ex=604800)
        return result

    async def get_master_by_niks_cached(self, niks):
        if not niks:
            return {}
        result, missing_niks = {}, []
        for nik in niks:
            cached = await self.redis.get(f"master:{nik}")
            if cached:
                result[nik] = json.loads(cached)
            else:
                missing_niks.append(nik)

        if missing_niks:
            db_result = self.repository.get_master_by_niks(missing_niks)
            for nik, data in db_result.items():
                result[nik] = data
                await self.redis.set(f"master:{nik}", json.dumps(jsonable_encoder(data)), ex=2592000)
        return result

    async def get_manual_review_data(self, file_id, page):
        meta = self.repository.get_minio_path(file_id)
        if not meta:
            raise HTTPException(status_code=404, detail="File not found")
        if meta["is_sync"] != 1 and meta["sync_status"] != 2:
            raise HTTPException(
                status_code=409,
                detail="File has not been completely synchronized yet or do not need manual review.",
            )

        manual_rows, total_rows = self.repository.get_manual_review_data(
            file_id, page, page_size=self.PAGE_SIZE_MANUAL_DATA
        )
        incoming_ids = [str(r["id_incoming"]) for r in manual_rows]
        master_niks  = [r["nik_master"] for r in manual_rows if r["nik_master"]]

        parquet_map = await self.parquet_loader.load_rows(file_id, meta["minio_path"], incoming_ids)
        master_map  = await self.get_master_by_niks_cached(master_niks)

        manual_result = []
        for row in manual_rows:
            institution = parquet_map.get(str(row["id_incoming"]), {}).copy()
            institution.update({
                "match_score": row["match_score"],
                "match_result_desc": row["match_result_name"],
                "file_id": row["file_id"],
                "reason": row["reason"],
            })
            manual_result.append({"institution": institution, "master": master_map.get(row["nik_master"])})

        total_pages = (total_rows + self.PAGE_SIZE_SYNCHRONIZED - 1) // self.PAGE_SIZE_SYNCHRONIZED
        return {
            "page": page, "page_size": self.PAGE_SIZE_GRADED,
            "total_rows": total_rows, "total_pages": total_pages,
            "has_next": page < total_pages, "has_prev": page > 1,
            "data": manual_result,
        }

    def mark_match_unmatch(self, id_incoming, file_id, match_status):
        # BEFORE_STATE: ambil match_result sebelum diubah
        before = self.repository.get_match_result_before(id_incoming, file_id)

        if match_status == MatchStatus.MANUAL_MATCH:
            updated = self.repository.mark_manual_match(id_incoming=id_incoming, file_id=file_id)
            action  = "MARK_MANUAL_MATCH"
            after   = {"match_result": 4}
        elif match_status == MatchStatus.MANUAL_UNMATCH:
            updated = self.repository.mark_manual_unmatch(id_incoming=id_incoming, file_id=file_id)
            action  = "MARK_MANUAL_UNMATCH"
            after   = {"match_result": 5}
        else:
            raise ValueError("Invalid match_status")

        # Catat audit dengan before_state dan after_state
        self._audit.log_audit_event(
            actor_org_id=file_id,
            action=action,
            resource_type="INSTITUTION",
            resource_id=id_incoming,
            result="SUCCESS",
            before_state=json.dumps(before),
            after_state=json.dumps(after),
        )

        return {
            "success": True,
            "updated_rows": updated,
            "file_id": file_id,
            "id_incoming": id_incoming,
        }

    def mark_as_completed(self, file_id):
        # BEFORE_STATE: ambil sync_status sebelum file di-complete
        before  = self.repository.get_file_status_before(file_id)
        updated = self.repository.mark_as_completed(file_id=file_id)
        after   = {"sync_status": 3, "is_sync": 1}

        try:
            import urllib.parse
            with self.repository.engine.begin() as conn:
                # Ambil data grade_code dan institution_name untuk URL Preview
                row = conn.execute(
                    text("""
                        SELECT rg.grade_code, uf.institution_name 
                        FROM uploaded_files uf
                        LEFT JOIN ref_grades rg ON uf.grade = rg.grade_id
                        WHERE uf.file_id = :file_id
                    """),
                    {"file_id": file_id}
                ).fetchone()
                
                grade_code = row[0] if row and row[0] else "Unknown"
                inst_name = row[1] if row and row[1] else "Institution"
                
                safe_grade = urllib.parse.quote(str(grade_code))
                safe_name = urllib.parse.quote(str(inst_name))
                
                # URL lengkap dengan parameter
                preview_url = f"/batch-synchronization/preview?file_id={file_id}&grade={safe_grade}&name={safe_name}"

                conn.execute(
                    text("""
                        UPDATE uploaded_files 
                        SET preview_url = :p_url
                        WHERE file_id = :file_id
                    """),
                    {"file_id": file_id, "p_url": preview_url}
                )
        except Exception as e:
            print(f"Gagal generate preview_url saat mark_as_complete: {e}")
            
        # Catat audit dengan before_state dan after_state
        self._audit.log_audit_event(
            actor_org_id=file_id,
            action="MARK_FILE_COMPLETED",
            resource_type="FILE",
            resource_id=file_id,
            result="SUCCESS",
            before_state=json.dumps(before),
            after_state=json.dumps({"sync_status": 3, **updated}),
        )

        generate_export_csv.apply_async(args=[file_id], queue="export_queue")

        return {
            "success": True,
            "updated_rows": updated,
            "file_id": file_id,
            "message": "File marked as completed. CSV export is generating in the background.",
        }

    def get_export_status(self, file_id):
        query = "SELECT export_status FROM uploaded_files WHERE file_id = :file_id"
        with self.repository.engine.connect() as conn:
            result = conn.execute(text(query), {"file_id": file_id}).scalar()
        if not result:
            raise HTTPException(status_code=404, detail="File not found")
        return {"file_id": file_id, "export_status": result}

    def get_export_download_url(self, file_id, export_type):
        query = """
            SELECT export_match_path, export_unmatch_path, export_status, institution_name
            FROM uploaded_files WHERE file_id = :file_id
        """
        with self.repository.engine.connect() as conn:
            row = conn.execute(text(query), {"file_id": file_id}).mappings().first()

        if not row or row["export_status"] != "READY":
            raise HTTPException(status_code=400, detail="Export file is not ready yet")

        object_name = row["export_match_path"] if export_type == "match" else row["export_unmatch_path"]
        if not object_name:
            raise HTTPException(status_code=404, detail=f"{export_type} file path is empty")

        institution_name   = row["institution_name"] or "Institution"
        safe_name          = institution_name.replace(" ", "_").replace("/", "_")
        tz_jakarta         = zoneinfo.ZoneInfo("Asia/Jakarta")
        current_timestamp  = datetime.now(tz_jakarta).strftime("%Y%m%d_%H%M%S")
        download_filename  = f"{safe_name}_{export_type}_{current_timestamp}.csv"

        url = self.minio_client.presigned_get_object(
            self.bucket_name, object_name,
            expires=timedelta(minutes=15),
            response_headers={"response-content-disposition": f'attachment; filename="{download_filename}"'},
        )
        return {"url": url, "filename": download_filename}

    def get_summary_dashboard(self):
        return {"data": self.repository.get_summary_dashboard()}