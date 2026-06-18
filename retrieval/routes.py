from fastapi import APIRouter, Request, Query
from .handler import RetrieveDataHandler
from audit.audit_service import AuditService
from util.parquet_loader import ParquetLoader
from pydantic import BaseModel
from .enum import MatchStatus


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

    def setup_routes(self):

        @self.router.get("/graded_files")
        async def get_graded_files(
            request: Request,
            page: int = Query(default=1, ge=1)
        ):
            self._get_audit(request).log_access_event(
                action="VIEW_GRADED_FILES_LIST",
                resource_type="LIST_VIEW",
                resource_id=f"page_{page}",
                ip_address=self._client_ip(request),
                result="SUCCESS",
            )
            handler = RetrieveDataHandler(request.app.state.starrocks_engine)
            return handler.get_graded_files(page)

        # ISSUE #6 FIX: endpoint ini sebelumnya tidak di-log sama sekali
        @self.router.get("/synchronized_files")
        async def get_synchronized_data(
            request: Request,
            page: int = Query(..., ge=1),
            institution_name: str = Query(...),
            grade: str = Query(...),
            sync_status: str = Query(...),
        ):
            self._get_audit(request).log_access_event(
                action="VIEW_SYNCHRONIZED_FILES",
                resource_type="LIST_VIEW",
                resource_id=f"page_{page}",
                ip_address=self._client_ip(request),
                result="SUCCESS",
            )
            handler = RetrieveDataHandler(request.app.state.starrocks_engine)
            return handler.get_synchronized_files(
                page=page,
                institution_name=institution_name,
                grade=grade,
                sync_status=sync_status,
            )

        # ISSUE #6 FIX
        @self.router.get("/history_data")
        async def get_history_data(
            request: Request,
            page: int = Query(..., ge=1),
            institution_name: str = Query(...),
            start_date: str = Query(...),
            end_date: str = Query(...),
        ):
            self._get_audit(request).log_access_event(
                action="VIEW_HISTORY_DATA",
                resource_type="LIST_VIEW",
                resource_id=f"page_{page}",
                ip_address=self._client_ip(request),
                result="SUCCESS",
            )
            handler = RetrieveDataHandler(request.app.state.starrocks_engine)
            return handler.get_history_data(
                page=page,
                institution_name=institution_name,
                start_date=start_date,
                end_date=end_date,
            )

        # ISSUE #6 FIX
        @self.router.get("/preview-data/{file_id}")
        async def preview_data(file_id: str, request: Request):
            self._get_audit(request).log_access_event(
                action="VIEW_PREVIEW_DATA",
                resource_type="FILE",
                resource_id=file_id,
                ip_address=self._client_ip(request),
                result="SUCCESS",
            )
            handler = RetrieveDataHandler(
                engine=request.app.state.starrocks_engine,
                parquet_loader=ParquetLoader(
                    request.app.state.minio_client,
                    request.app.state.raw_bucket,
                    redis=request.app.state.redis,
                ),
                redis=request.app.state.redis,
            )
            return await handler.get_preview_data(file_id=file_id)

        # ISSUE #6 FIX
        @self.router.get("/manual-review-data")
        async def manual_review_data(
            request: Request,
            file_id: str = Query(...),
            page: int = Query(..., ge=1),
        ):
            self._get_audit(request).log_access_event(
                action="VIEW_MANUAL_REVIEW_DATA",
                resource_type="FILE",
                resource_id=file_id,
                ip_address=self._client_ip(request),
                result="SUCCESS",
            )
            handler = RetrieveDataHandler(
                engine=request.app.state.starrocks_engine,
                parquet_loader=ParquetLoader(
                    request.app.state.minio_client,
                    request.app.state.raw_bucket,
                    redis=request.app.state.redis,
                ),
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
        ):
            self._get_audit(request).log_access_event(
                action="MARK_MATCH_STATUS",
                resource_type="FILE",
                resource_id=file_id,
                ip_address=self._client_ip(request),
                result="SUCCESS",
            )
            handler = RetrieveDataHandler(engine=request.app.state.starrocks_engine)
            return handler.mark_match_unmatch(
                file_id=file_id,
                id_incoming=id_incoming,
                match_status=payload.match_status,
            )

        # ISSUE #6 FIX: PATCH endpoint — aksi write paling penting di-audit
        @self.router.patch("/mark-as-completed/files/{file_id}")
        async def mark_as_completed(file_id: str, request: Request):
            self._get_audit(request).log_access_event(
                action="MARK_FILE_COMPLETED",
                resource_type="FILE",
                resource_id=file_id,
                ip_address=self._client_ip(request),
                result="SUCCESS",
            )
            handler = RetrieveDataHandler(
                engine=request.app.state.starrocks_engine,
                minio_client=request.app.state.minio_client,
                bucket_name=request.app.state.raw_bucket,
            )
            return handler.mark_as_completed(file_id=file_id)

        @self.router.get("/files/{file_id}/export-status")
        async def export_status(file_id: str, request: Request):
            # ISSUE #6 FIX
            self._get_audit(request).log_access_event(
                action="VIEW_EXPORT_STATUS",
                resource_type="FILE",
                resource_id=file_id,
                ip_address=self._client_ip(request),
                result="SUCCESS",
            )
            handler = RetrieveDataHandler(engine=request.app.state.starrocks_engine)
            return handler.get_export_status(file_id)

        @self.router.get("/files/{file_id}/export/download")
        async def download_export(
            file_id: str,
            request: Request,
            type: str = Query(..., description="Tipe file: 'match' atau 'unmatch'"),
        ):
            if type not in ["match", "unmatch"]:
                return {"error": "Type must be 'match' or 'unmatch'"}

            # ISSUE #6 FIX
            self._get_audit(request).log_access_event(
                action=f"DOWNLOAD_EXPORT_{type.upper()}",
                resource_type="FILE",
                resource_id=file_id,
                ip_address=self._client_ip(request),
                result="SUCCESS",
            )
            handler = RetrieveDataHandler(
                engine=request.app.state.starrocks_engine,
                minio_client=request.app.state.minio_client,
                bucket_name=request.app.state.raw_bucket,
            )
            return handler.get_export_download_url(file_id, type)

        # ISSUE #6 FIX
        @self.router.get("/summary_dashboard")
        async def get_summary_dashboard(request: Request):
            self._get_audit(request).log_access_event(
                action="VIEW_SUMMARY_DASHBOARD",
                resource_type="DASHBOARD",
                resource_id="summary",
                ip_address=self._client_ip(request),
                result="SUCCESS",
            )
            handler = RetrieveDataHandler(request.app.state.starrocks_engine)
            return handler.get_summary_dashboard()