from fastapi import APIRouter, Request, Query
from .handler import RetrieveDataHandler
from audit.audit_service import AuditService

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