import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from audit.tasks import log_api_latency_task

class LatencyTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Eksekusi endpoint
        response = await call_next(request)
        
        # Kalkulasi latency dalam milidetik
        process_time_ms = int((time.time() - start_time) * 1000)
        
        # Ambil IP address dari request
        client_ip = request.client.host if request.client else "127.0.0.1"
        endpoint = request.url.path
        method = request.method
        
        # Opsional: Jangan log endpoint statis, root, atau halaman audit itu sendiri agar DB tidak penuh
        if not endpoint.startswith(("/audit", "/docs", "/openapi.json")):
            # Kirim data secara asynchronous via Celery
            log_api_latency_task.delay(
                action=method,                       # Contoh: GET, POST
                resource_type="API_ENDPOINT",
                resource_id=endpoint,                # Contoh: /retrieval/search
                ip_address=client_ip,
                result="SUCCESS" if response.status_code < 400 else "FAILED",
                latency_ms=process_time_ms
            )
            
        return response