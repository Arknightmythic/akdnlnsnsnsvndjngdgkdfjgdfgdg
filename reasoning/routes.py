from fastapi import APIRouter, Query, Request

class ReasoningRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()

    def setup_routes(self):
        @self.router.post("/run/")
        def run_reasoning(request: Request, file_id: str = Query(..., description="File ID to filter")):
            handler = request.app.state.reasoning_handler
            return handler.run_reasoning(file_id)

        @self.router.post("/test/")
        def test_reasoning(request: Request, file_id: str = Query(..., description="File ID to filter")):
            handler = request.app.state.reasoning_handler
            return handler.test_reasoning(file_id)

        @self.router.post("/enqueue/")
        def enqueue_reasoning(request: Request, file_id: str = Query(..., description="File ID to enqueue for reasoning")):
            handler = request.app.state.reasoning_handler
            return handler.enqueue_reasoning(file_id)

        @self.router.get("/task/{task_id}")
        def get_task_status(task_id: str):
            from reasoning.celery_app import celery_app
            result = celery_app.AsyncResult(task_id)
            return {"task_id": task_id, "status": result.status, "result": str(result.result)}
