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