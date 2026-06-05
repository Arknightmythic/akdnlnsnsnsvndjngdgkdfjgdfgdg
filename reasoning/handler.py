from .reasoning_service import ReasoningService


class ReasoningHandler:
    def __init__(self, engine):
        """
        Handler utama untuk orkestrasi reasoning service.
        Hanya membutuhkan engine DB — tidak ada MinIO dependency.
        """
        self.engine = engine
        self.reasoning_service = ReasoningService(engine)



    def run_reasoning_by_id(self, mm_id: int) -> dict:
        """
        Menjalankan AI reasoning untuk satu baris spesifik di manual_matches.
        """
        return self.reasoning_service.process_reasoning_by_id(mm_id=mm_id)



    def test_reasoning(self, file_id: str):
        """Dry run — tidak menyentuh DB, hanya test pipeline data + LLM."""
        print(f"[Reasoning] Dry run for file_id: {file_id}")
        return self.reasoning_service.process_reasoning(file_id, dry_run=True)


