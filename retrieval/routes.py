from fastapi import APIRouter, Request, Query, BackgroundTasks
from fastapi import APIRouter, Request, Query, BackgroundTasks
from .handler import RetrieveDataHandler
from audit.writer import AuditWriter
from util.parquet_loader import ParquetLoader
from pydantic import BaseModel
from .enum import MatchStatus
import json


class MarkMatchRequest(BaseModel):
    match_status: MatchStatus


class RetrieveDataRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()

    # Helper agar tidak mengulang boilerplate di setiap endpoint
    def _get_audit(self, request: Request) -> AuditService:
        return AuditService(request.app.state.starrocks_engine)

    def _client_ip(self, request: Request) -> str:
        return request.client.host if request.client else "unknown"
    
    async def push_audit_to_redis(self, redis_client, event_data: dict):
        # Push data log ke Redis list
        await redis_client.rpush("audit_access_logs", json.dumps(event_data))

    def _log_access_async(self, request: Request, background_tasks: BackgroundTasks, action: str, resource_type: str, resource_id: str):
        event_data = {
            "actor_user_id": "anonymous_poc",
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "ip_address": self._client_ip(request),
            "result": "SUCCESS",
            "latency_ms": 0
        }
        background_tasks.add_task(self.push_audit_to_redis, request.app.state.redis, event_data)

    def setup_routes(self):

        # 2. TERAPKAN KE SEMUA ENDPOINT
        @self.router.get("/graded_files")
        async def get_graded_files(
            request: Request,
            background_tasks: BackgroundTasks, # Wajib tambahkan ini di setiap endpoint
            page: int = Query(default=1, ge=1)
        ):
            self._log_access_async(request, background_tasks, "VIEW_GRADED_FILES_LIST", "LIST_VIEW", f"page_{page}")
            handler = RetrieveDataHandler(request.app.state.starrocks_engine)
            return handler.get_graded_files(page)

        @self.router.get("/synchronized_files")
        async def get_synchronized_data(
            request: Request,
            background_tasks: BackgroundTasks, # Wajib tambahkan
            page: int = Query(..., ge=1),
            institution_name: str = Query(...),
            grade: str = Query(...),
            sync_status: str = Query(...),
        ):
            self._log_access_async(request, background_tasks, "VIEW_SYNCHRONIZED_FILES", "LIST_VIEW", f"page_{page}")
            handler = RetrieveDataHandler(request.app.state.starrocks_engine)
            return handler.get_synchronized_files(page=page, institution_name=institution_name, grade=grade, sync_status=sync_status)

        # ISSUE #6 FIX
        @self.router.get("/history_data")
        async def get_history_data(
            request: Request,
            background_tasks: BackgroundTasks,
            background_tasks: BackgroundTasks,
            page: int = Query(..., ge=1),
            institution_name: str = Query(...),
            start_date: str = Query(...),
            end_date: str = Query(...),
        ):
            self._log_access_async(request, background_tasks, "VIEW_HISTORY_DATA", "LIST_VIEW", f"page_{page}")
            handler = RetrieveDataHandler(request.app.state.starrocks_engine)
            return handler.get_history_data(
                page=page,
                institution_name=institution_name,
                start_date=start_date,
                end_date=end_date,
                end_date=end_date,
            )

        # ISSUE #6 FIX
        @self.router.get("/preview-data/{file_id}")
        async def preview_data(file_id: str, request: Request, background_tasks: BackgroundTasks):
            self._log_access_async(request, background_tasks, "VIEW_PREVIEW_DATA", "FILE", file_id)
            handler = RetrieveDataHandler(
                engine=request.app.state.starrocks_engine,
                parquet_loader=ParquetLoader(
                    request.app.state.minio_client,
                    request.app.state.raw_bucket,
                    redis=request.app.state.redis,
                    redis=request.app.state.redis,
                ),
                redis=request.app.state.redis,
                redis=request.app.state.redis,
            )
            return await handler.get_preview_data(file_id=file_id)

        # ISSUE #6 FIX
        @self.router.get("/manual-review-data")
        async def manual_review_data(
            request: Request,
            background_tasks: BackgroundTasks,
            background_tasks: BackgroundTasks,
            file_id: str = Query(...),
            page: int = Query(..., ge=1),
        ):
            self._log_access_async(request, background_tasks, "VIEW_MANUAL_REVIEW_DATA", "FILE", file_id)
            handler = RetrieveDataHandler(
                engine=request.app.state.starrocks_engine,
                parquet_loader=ParquetLoader(
                    request.app.state.minio_client,
                    request.app.state.raw_bucket,
                    redis=request.app.state.redis,
                    redis=request.app.state.redis,
                ),
                redis=request.app.state.redis,
                redis=request.app.state.redis,
            )
            return await handler.get_manual_review_data(file_id=file_id, page=page)

        # ISSUE #6 FIX: PATCH endpoint — ini aksi write, lebih penting di-audit
        @self.router.patch("/files/{file_id}/data/{id_incoming}/match-status")
        async def mark_manual_match_unmatch(
            file_id: str,
            id_incoming: str,
            payload: MarkMatchRequest,
            request: Request,
            background_tasks: BackgroundTasks,
        ):
            self._log_access_async(request, background_tasks, "MARK_MATCH_STATUS", "FILE", file_id)
            handler = RetrieveDataHandler(engine=request.app.state.starrocks_engine)
            return handler.mark_match_unmatch(
                file_id=file_id,
                id_incoming=id_incoming,
                match_status=payload.match_status,
                match_status=payload.match_status,
            )

        # ISSUE #6 FIX: PATCH endpoint — aksi write paling penting di-audit
        @self.router.patch("/mark-as-completed/files/{file_id}")
        async def mark_as_completed(file_id: str, request: Request, background_tasks: BackgroundTasks):
            self._log_access_async(request, background_tasks, "MARK_FILE_COMPLETED", "FILE", file_id)
            handler = RetrieveDataHandler(
                engine=request.app.state.starrocks_engine,
                minio_client=request.app.state.minio_client,
                bucket_name=request.app.state.raw_bucket,
                minio_client=request.app.state.minio_client,
                bucket_name=request.app.state.raw_bucket,
            )
            return handler.mark_as_completed(file_id=file_id)

        @self.router.get("/files/{file_id}/export-status")
        async def export_status(file_id: str, request: Request, background_tasks: BackgroundTasks):
            # ISSUE #6 FIX
            self._log_access_async(request, background_tasks, "VIEW_EXPORT_STATUS", "FILE", file_id)
            handler = RetrieveDataHandler(engine=request.app.state.starrocks_engine)
            return handler.get_export_status(file_id)

        @self.router.get("/files/{file_id}/export/download")
        async def download_export(
            file_id: str,
            request: Request,
            background_tasks: BackgroundTasks,
            type: str = Query(..., description="Tipe file: 'match' atau 'unmatch'"),
        ):
            if type not in ["match", "unmatch"]:
                return {"error": "Type must be 'match' or 'unmatch'"}

            # ISSUE #6 FIX
            self._log_access_async(request, background_tasks, f"DOWNLOAD_EXPORT_{type.upper()}", "FILE", file_id)
            handler = RetrieveDataHandler(
                engine=request.app.state.starrocks_engine,
                minio_client=request.app.state.minio_client,
                bucket_name=request.app.state.raw_bucket,
                bucket_name=request.app.state.raw_bucket,
            )
            return handler.get_export_download_url(file_id, type)

        # ISSUE #6 FIX
        @self.router.get("/summary_dashboard")
        async def get_summary_dashboard(request: Request, background_tasks: BackgroundTasks):
            self._log_access_async(request, background_tasks, "VIEW_SUMMARY_DASHBOARD", "DASHBOARD", "summary")
            handler = RetrieveDataHandler(request.app.state.starrocks_engine)
            return handler.get_summary_dashboard()