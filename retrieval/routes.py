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

    def setup_routes(self):

        @self.router.get("/graded_files")
        async def get_graded_files(
            request: Request,
            page: int = Query(default=1, ge=1)
        ):
            # Log Access Event
            client_ip = request.client.host if request.client else "unknown"
            audit_service = AuditService(request.app.state.starrocks_engine)
            audit_service.log_access_event(
                action="VIEW_GRADED_FILES_LIST",
                resource_type="LIST_VIEW",
                resource_id=f"page_{page}",
                ip_address=client_ip,
                result="SUCCESS"
            )
            handler = RetrieveDataHandler(
                request.app.state.starrocks_engine
            )

            return handler.get_graded_files(page)
        
        @self.router.get("/synchronized_files")
        async def get_synchronized_data(
            request: Request,
            page: int = Query(..., ge=1),
            institution_name: str = Query(...),
            grade: str = Query(...),
            sync_status: str = Query(...)
        ):
            handler = RetrieveDataHandler(
                request.app.state.starrocks_engine
            )

            return handler.get_synchronized_files(
                page=page,
                institution_name=institution_name,
                grade=grade,
                sync_status=sync_status
            )
        
        @self.router.get("/history_data")
        async def get_history_data(
            request: Request,
            page: int = Query(..., ge=1),
            institution_name: str = Query(...),
            start_date: str = Query(...),
            end_date: str = Query(...),
        ):
            handler = RetrieveDataHandler(
                request.app.state.starrocks_engine
            )

            return handler.get_history_data(
                page=page,
                institution_name=institution_name,
                start_date=start_date,
                end_date=end_date
            )
        
        @self.router.get("/preview-data/{file_id}")
        async def preview_data(file_id: str, request: Request):

            handler = RetrieveDataHandler(
                engine=request.app.state.starrocks_engine,
                parquet_loader=ParquetLoader(
                    request.app.state.minio_client,
                    request.app.state.raw_bucket,
                    redis=request.app.state.redis
                ),
                redis=request.app.state.redis
            )

            return await handler.get_preview_data(
                file_id=file_id,
            )
        
        @self.router.get("/manual-review-data")
        async def manual_review_data(
            request: Request,
            file_id: str = Query(...),
            page: int = Query(..., ge=1),
        ):

            handler = RetrieveDataHandler(
                engine=request.app.state.starrocks_engine,
                parquet_loader=ParquetLoader(
                    request.app.state.minio_client,
                    request.app.state.raw_bucket,
                    redis=request.app.state.redis
                ),
                redis=request.app.state.redis
            )

            return await handler.get_manual_review_data(
                file_id=file_id, page=page
            )
        
        @self.router.patch("/files/{file_id}/data/{id_incoming}/match-status")
        async def mark_manual_match_unmatch(
            file_id: str,
            id_incoming: str,
            payload: MarkMatchRequest,
            request: Request
        ):
            handler = RetrieveDataHandler(
                engine=request.app.state.starrocks_engine,
            )

            return handler.mark_match_unmatch(
                file_id=file_id,
                id_incoming=id_incoming,
                match_status=payload.match_status
            )
        
        @self.router.patch("/mark-as-completed/files/{file_id}")
        async def mark_as_completed(
            file_id: str,
            request: Request
        ):
            handler = RetrieveDataHandler(
                engine=request.app.state.starrocks_engine,
            )

            return handler.mark_as_completed(
                file_id=file_id,
            )
        
        @self.router.get("/summary_dashboard")
        async def get_summary_dashboard(
            request: Request,
        ):
            handler = RetrieveDataHandler(
                request.app.state.starrocks_engine
            )

            return handler.get_summary_dashboard()