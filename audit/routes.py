from fastapi import APIRouter
from .tasks import execute_audit_retention

class AuditRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()

    def setup_routes(self):
        @self.router.post("/retention/trigger")
        async def trigger_retention():
            # Memanggil fungsi celery menggunakan .delay()
            # Ini akan mengirim pesan ke Redis, dan FastAPI langsung memberikan response
            # tanpa harus menunggu proses hapus data di StarRocks selesai.
            task = execute_audit_retention.delay()
            
            return {
                "message": "Retention task has been queued successfully",
                "task_id": task.id,
                "status": "Queued"
            }