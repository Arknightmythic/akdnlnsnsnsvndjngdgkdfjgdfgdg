from fastapi import APIRouter, Request, Query
from typing import Optional
from .tasks import execute_audit_retention
import worker
from .dashboard_service import DashboardService

class AuditRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()

    def setup_routes(self):
        @self.router.post("/retention/trigger")
        async def trigger_retention():
            task = execute_audit_retention.delay()
            return {"message": "Retention queued", "task_id": task.id, "status": "Queued"}

        @self.router.get("/audit/summary")
        async def get_audit_summary(request: Request, period: str = "daily", start_date: Optional[str] = None, end_date: Optional[str] = None):
            return DashboardService(request.app.state.starrocks_engine).get_audit_summary(period, start_date, end_date)

        @self.router.get("/audit/latency-chart")
        async def get_latency_chart(request: Request, period: str = "daily", start_date: Optional[str] = None, end_date: Optional[str] = None):
            return DashboardService(request.app.state.starrocks_engine).get_latency_chart(period, start_date, end_date)

        @self.router.get("/retention/summary")
        async def get_retention_summary(request: Request):
            return DashboardService(request.app.state.starrocks_engine).get_retention_summary()

        @self.router.get("/audit/logs")
        async def get_audit_logs(request: Request, page: int = Query(default=1, ge=1), period: str = "daily", start_date: Optional[str] = None, end_date: Optional[str] = None):
            return DashboardService(request.app.state.starrocks_engine).get_audit_logs_pagination(page, period, start_date, end_date)

        # [TAMBAHAN] Endpoint khusus Access Logs
        @self.router.get("/access/logs")
        async def get_access_logs(request: Request, page: int = Query(default=1, ge=1), period: str = "daily", start_date: Optional[str] = None, end_date: Optional[str] = None):
            return DashboardService(request.app.state.starrocks_engine).get_access_logs_pagination(page, period, start_date, end_date)