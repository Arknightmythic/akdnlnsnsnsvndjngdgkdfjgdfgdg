from fastapi import APIRouter, Request, HTTPException
from starlette import status
from starlette.responses import JSONResponse

from audit.audit_service import AuditService
from .repository import CustomMappingRepository, MASTER_MATCHING_COLUMNS
from .service import CustomMappingService
from .tasks import generate_field_mapping
from .api_schema import SaveMappingRequest, MappingStatusResponse


class CustomMappingRoutes:
    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()
        print("Custom Mapping Routes initialized")

    def _build_service(self, request: Request) -> CustomMappingService:
        return CustomMappingService(
            engine=request.app.state.starrocks_engine,
            minio_client=request.app.state.minio_client,
            bucket_name=request.app.state.raw_bucket,
        )

    def setup_routes(self):

        # ── Step 2-6: user klik tombol 'custom grading' -> set grade 6 (kalau
        # belum) -> trigger Celery task generate_field_mapping (ekstrak kolom
        # + GenAI pairing). Idempoten: kalau task lagi PROCESSING, tolak dulu
        # daripada dispatch dobel. Task ini juga yang jalan kalau user klik
        # tombol "Regenerate" di layar review pairing.
        @self.router.post("/{file_id}/activate")
        def activate_custom_grading(request: Request, file_id: str):
            client_ip = request.client.host if request.client else "unknown"
            audit_service = AuditService(request.app.state.starrocks_engine)
            audit_service.log_access_event(
                action="ACCESS_CUSTOM_MAPPING_ACTIVATE",
                resource_type="ENDPOINT",
                resource_id=file_id,
                ip_address=client_ip,
                result="SUCCESS",
            )

            repo = CustomMappingRepository(request.app.state.starrocks_engine)
            uploaded_file = repo.get_uploaded_file(file_id)
            if not uploaded_file:
                raise HTTPException(status_code=404, detail="File not found")

            if uploaded_file["custom_mapping_task_status"] == "PROCESSING":
                raise HTTPException(
                    status_code=409,
                    detail="Proses generate mapping sedang berjalan untuk file ini.",
                )

            # File yang sudah auto-graded 6 oleh grader_service (fallback
            # grade F) gak perlu di-UPDATE ulang — cuma di-override kalau
            # user secara eksplisit maksa file grade lain jadi custom.
            if uploaded_file["grade"] != 6:
                repo.force_set_grade_6(file_id)

            task = generate_field_mapping.apply_async(
                args=[file_id], queue="custom_mapping_queue"
            )
            repo.set_custom_mapping_task_info(file_id, task.id, "PROCESSING")

            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "status": "PROCESSING",
                    "message": "Custom grading diaktifkan, AI sedang memetakan kolom.",
                    "file_id": file_id,
                },
            )

        # ── Step 7 (baca): frontend polling status task + ambil pairing buat
        # ditampilkan di layar review (termasuk daftar kolom incoming & master
        # yang valid, buat dropdown kalau user mau edit/tambah pairing manual).
        @self.router.get("/{file_id}", response_model=MappingStatusResponse)
        def get_custom_mapping(request: Request, file_id: str):
            repo = CustomMappingRepository(request.app.state.starrocks_engine)
            uploaded_file = repo.get_uploaded_file(file_id)
            if not uploaded_file:
                raise HTTPException(status_code=404, detail="File not found")

            incoming_columns = []
            if uploaded_file["custom_mapping_task_status"] in ("SUCCESS", "FAILED"):
                # Cuma coba baca kolom kalau task generate udah pernah selesai
                # (biar gak nge-hit MinIO percuma pas masih PROCESSING/IDLE).
                try:
                    service = self._build_service(request)
                    incoming_columns = service.get_incoming_columns(uploaded_file["minio_path"])
                except Exception:
                    incoming_columns = []

            active_pairs = repo.get_active_mapping(file_id)

            return {
                "file_id": file_id,
                "grade": uploaded_file["grade"],
                "is_custom_ready": bool(uploaded_file["is_custom_ready"]),
                "custom_mapping_task_status": uploaded_file["custom_mapping_task_status"],
                "incoming_columns": incoming_columns,
                "master_columns": MASTER_MATCHING_COLUMNS,
                "pairs": [dict(p) for p in active_pairs],
            }

        # ── Step 7 (tulis): user konfirmasi pairing final + weight. Sukses ->
        # is_custom_ready=1, sehingga POST /match/?file_id= (endpoint yang
        # sudah ada di processing/routes.py) bisa langsung dipanggil setelah
        # ini tanpa endpoint baru — handler.py sudah otomatis routing grade 6
        # ke process_custom_matching_job begitu is_custom_ready=1.
        @self.router.put("/{file_id}")
        def save_custom_mapping(request: Request, file_id: str, payload: SaveMappingRequest):
            client_ip = request.client.host if request.client else "unknown"
            audit_service = AuditService(request.app.state.starrocks_engine)
            audit_service.log_access_event(
                action="ACCESS_CUSTOM_MAPPING_SAVE",
                resource_type="ENDPOINT",
                resource_id=file_id,
                ip_address=client_ip,
                result="SUCCESS",
            )

            service = self._build_service(request)
            try:
                result = service.save_pairs(
                    file_id, [p.model_dump() for p in payload.pairs]
                )
            except LookupError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

            return result