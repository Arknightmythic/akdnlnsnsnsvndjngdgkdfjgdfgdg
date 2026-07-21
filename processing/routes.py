import asyncio
import json
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette import status
from starlette.responses import JSONResponse
from audit.audit_service import AuditService
from .tasks import run_matching_task
from processing.repository import StarrocksService


class MatchFileRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()
        print("Routes initialized")

    def setup_routes(self):

        @self.router.post("/")
        def process_file(request: Request, file_id: str):
            client_ip = request.client.host if request.client else "unknown"
            audit_service = AuditService(request.app.state.starrocks_engine)
            audit_service.log_access_event(
                action="ACCESS_MATCH_ENDPOINT",
                resource_type="ENDPOINT",
                resource_id=file_id,
                ip_address=client_ip,
                result="SUCCESS"
            )

            starrocks_service = StarrocksService(request.app.state.starrocks_engine)

            # 1. Tandai PROCESSING SEBELUM dispatch ke Celery. Urutan ini penting:
            # kalau apply_async() dipanggil dulu, untuk file kecil worker bisa saja
            # sudah selesai dan menulis status SUCCESS/FAILED sebelum baris ini
            # sempat jalan — status akhirnya balik tertimpa jadi PROCESSING selamanya.
            # start_new_matching_run() juga membersihkan reasoning_task_status,
            # preview_url, investigate_url, dan export_status — supaya file yang
            # DI-RE-MATCH (mis. setelah regenerate custom mapping) tidak menyisakan
            # kombinasi status basi dari run sebelumnya (matching PROCESSING tapi
            # reasoning/preview masih menunjukkan hasil lama yang sudah SUCCESS).
            starrocks_service.start_new_matching_run(file_id)

            # 2. Baru lempar ke Celery dan dapatkan task_id
            task = run_matching_task.apply_async(args=[file_id], queue="matching_queue")

            # 3. Simpan task_id SAJA (tidak menyentuh status) — kalau worker sudah
            # keburu selesai di titik ini, status SUCCESS/FAILED yang sudah ditulis
            # worker tidak boleh tertimpa balik ke PROCESSING.
            starrocks_service.set_matching_task_id(file_id, task.id)

            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "status": "PROCESSING",
                    "message": "Data matching sedang berjalan di background.",
                    "file_id": file_id
                }
            )

        @self.router.get("/status/{file_id}")
        def get_match_status(request: Request, file_id: str):
            starrocks_service = StarrocksService(request.app.state.starrocks_engine)
            file_data = starrocks_service.get_uploaded_file(file_id)

            if not file_data:
                return JSONResponse(status_code=404, content={"message": "File not found"})

            return {
                "file_id": file_id,
                "matching_task_status": file_data.get("matching_task_status", "IDLE")
            }

        # --- ENDPOINT BARU: Menarik Riwayat Log (History) ---
        @self.router.get("/logs/{file_id}")
        async def get_match_logs(request: Request, file_id: str):
            # 1. Ambil status terkini dari database
            starrocks_service = StarrocksService(request.app.state.starrocks_engine)
            file_data = starrocks_service.get_uploaded_file(file_id)

            if not file_data:
                return JSONResponse(status_code=404, content={"message": "File not found"})

            current_status = file_data.get("matching_task_status", "IDLE")

            # 2. Ambil riwayat log dari Redis
            redis = request.app.state.redis
            redis_key = f"matching_log:{file_id}"
            
            # Tarik semua data dari index 0 sampai terakhir (-1)
            entries = await redis.lrange(redis_key, 0, -1)

            logs = []
            if entries:
                for raw in entries:
                    try:
                        payload = json.loads(raw)
                        # Sembunyikan sentinel __DONE__ agar tidak tampil di frontend
                        if payload.get("message") != "__DONE__":
                            logs.append(payload)
                    except Exception:
                        logs.append({"message": str(raw), "level": "INFO"})

            return {
                "matching_task_status": current_status,
                "logs": logs
            }

        @self.router.get("/stream/{file_id}")
        async def stream_matching_log(request: Request, file_id: str):
            redis = request.app.state.redis
            redis_key = f"matching_log:{file_id}"

            async def event_generator():
                # cursor: index Redis list berikutnya yang belum dibaca
                cursor = 0

                # Timeout maksimal 15 menit — aman untuk file 1M+ rows
                MAX_WAIT = 15 * 60
                waited = 0

                while waited < MAX_WAIT:
                    # Cek apakah client sudah disconnect
                    if await request.is_disconnected():
                        break

                    # Baca semua entry baru sejak cursor terakhir
                    entries = await redis.lrange(redis_key, cursor, -1)

                    if entries:
                        for raw in entries:
                            cursor += 1
                            try:
                                payload = json.loads(raw)
                            except Exception:
                                payload = {"message": raw, "level": "INFO"}

                            # Sentinel: worker selesai → tutup stream
                            if payload.get("message") == "__DONE__":
                                # Kirim event DONE ke frontend sebelum tutup
                                done_event = json.dumps({
                                    "message": "__DONE__",
                                    "level": payload.get("level", "SUCCESS"),
                                })
                                yield f"data: {done_event}\n\n"
                                return

                            yield f"data: {json.dumps(payload)}\n\n"

                        # Reset waited karena ada data masuk
                        waited = 0
                    else:
                        # Tidak ada data baru — tunggu sebentar
                        await asyncio.sleep(0.5)
                        waited += 0.5

                # Timeout: kirim event error dan tutup
                yield f"data: {json.dumps({'message': 'Stream timeout.', 'level': 'ERROR'})}\n\n"

            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={
                    # Mencegah buffering di proxy/nginx
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )