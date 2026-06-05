from fastapi import APIRouter, Query, Request

class ReasoningRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()
        print("Reasoning Routes initialized")

    def setup_routes(self):
        @self.router.post("/run/")
        def run_reasoning(request: Request, file_id: str = Query(..., description="File ID to filter")):
            handler = request.app.state.reasoning_handler
            return handler.run_reasoning(file_id)

        @self.router.post("/test/")
        def test_reasoning(request: Request, file_id: str = Query(..., description="File ID to filter")):
            handler = request.app.state.reasoning_handler
            return handler.test_reasoning(file_id)

        @self.router.post("/scheduler/start")
        def start_scheduler(request: Request):
            scheduler = request.app.state.reasoning_scheduler
            scheduler.start()
            return {"message": "Scheduler started", "status": scheduler.status()}

        @self.router.post("/scheduler/stop")
        def stop_scheduler(request: Request):
            scheduler = request.app.state.reasoning_scheduler
            scheduler.stop()
            return {"message": "Scheduler stopped", "status": scheduler.status()}

        @self.router.get("/scheduler/status")
        def scheduler_status(request: Request):
            scheduler = request.app.state.reasoning_scheduler
            return scheduler.status()
