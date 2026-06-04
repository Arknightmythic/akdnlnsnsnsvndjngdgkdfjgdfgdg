from fastapi import APIRouter, Request, Query
from .handler import RetrieveDataHandler

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