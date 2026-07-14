import os
import tempfile
import polars as pl
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from .schema import FieldMappingOutput
from .prompt import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from .repository import CustomMappingRepository, MASTER_MATCHING_COLUMNS

# BLOCKING_ANCHOR_FIELDS didefinisikan di processing/custom_query_builder.py
# (dipakai di sana untuk generate JOIN dinamis). Diimpor lagi di sini supaya
# validasi "minimal 1 anchor blocking" pas user save weight (step 7) selalu
# sinkron dengan field yang BENERAN dipakai matching engine — satu sumber
# kebenaran, gak didefinisikan ulang manual di dua tempat.
from processing.custom_query_builder import BLOCKING_ANCHOR_FIELDS

load_dotenv()


class CustomMappingService:
    """
    Service untuk grade 6 ('others') custom grading flow:
    ekstrak kolom file incoming -> minta GenAI memetakan ke kolom master ->
    simpan hasil pairing (weight-nya baru diisi user di step berikutnya, lewat
    endpoint terpisah, bukan di sini).
    """

    def __init__(self, engine, minio_client, bucket_name):
        self.repo = CustomMappingRepository(engine)
        self.minio_client = minio_client
        self.bucket_name = bucket_name

        # Setup LLM mengikuti pola persis reasoning/reasoning_service.py supaya
        # provider (ollama/vllm) & env var konsisten di seluruh sistem.
        llm_provider = os.getenv("LLM_PROVIDER", "ollama").lower()
        base_url = os.getenv("OLLAMA_LOCAL_BASE_URL", "http://localhost:11434")
        if not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"

        if llm_provider == "vllm":
            self.llm = ChatOpenAI(
                model=os.getenv("VLLM_MODEL_NAME", "meta-llama/Meta-Llama-3-8B-Instruct"),
                temperature=0,
                base_url=base_url,
                api_key=os.getenv("OPENAI_API_KEY", "EMPTY"),
                max_tokens=1000,
            ).with_structured_output(FieldMappingOutput)
        else:
            self.llm = ChatOpenAI(
                model=os.getenv("OLLAMA_MODEL_NAME", "llama3.1:8b-instruct-q4_K_M"),
                temperature=0,
                base_url=base_url,
                api_key=os.getenv("OPENAI_API_KEY", "ollama"),
            ).with_structured_output(FieldMappingOutput)

    # ─── Helpers ──────────────────────────────────────────────────────────

    def get_incoming_columns(self, minio_path: str) -> list[str]:
        """
        Baca HANYA schema/header parquet dari MinIO, tanpa load seluruh data ke
        memory. Ini beda sengaja dari ObjectStorageService.load_parquet_from_minio
        (processing/minio_fetching_service.py) yang load + transform seluruh
        data — gak perlu buat sekadar ambil nama kolom, dan file custom bisa
        1M+ baris.
        """
        response = self.minio_client.get_object(self.bucket_name, minio_path)
        with tempfile.NamedTemporaryFile(suffix=".parquet") as tmp:
            for chunk in response.stream(32 * 1024):
                tmp.write(chunk)
            tmp.flush()
            schema = pl.read_parquet_schema(tmp.name)

        columns = [c.strip() for c in schema.keys()]
        # `id` adalah row index internal yang kita tambahkan sendiri saat upload
        # (lihat ingestion/handler.py: df.with_row_index(name="id")) — bukan
        # bagian dari data asli user, jadi gak relevan buat dipetakan.
        return [c for c in columns if c.lower() != "id"]

    def _validate_pairs(self, pairs, incoming_columns: list[str]) -> list[dict]:
        """
        Jangan percaya output LLM mentah-mentah. Filter supaya hanya pairing
        yang valid (master_column & incoming_column benar-benar ada di daftar
        asli) yang disimpan ke DB, dan cegah kolom dipakai dobel.
        """
        valid_master = set(MASTER_MATCHING_COLUMNS)
        valid_incoming = set(incoming_columns)

        seen_master = set()
        seen_incoming = set()
        cleaned = []

        for pair in pairs:
            if pair.master_column not in valid_master:
                print(f"[CustomMapping] Lewati pairing, master_column tidak valid: {pair.master_column}")
                continue
            if pair.incoming_column not in valid_incoming:
                print(f"[CustomMapping] Lewati pairing, incoming_column tidak valid: {pair.incoming_column}")
                continue
            if pair.master_column in seen_master or pair.incoming_column in seen_incoming:
                print(f"[CustomMapping] Lewati pairing duplikat: {pair.master_column} <-> {pair.incoming_column}")
                continue

            seen_master.add(pair.master_column)
            seen_incoming.add(pair.incoming_column)
            cleaned.append({
                "master_column": pair.master_column,
                "incoming_column": pair.incoming_column,
                "weight": None,  # diisi user nanti di step save weight (PUT /custom-mapping/{file_id})
                "confidence": round(pair.confidence, 2),
                "source": "GENAI",
            })

        return cleaned

    # ─── Main entrypoint ────────────────────────────────────────────────

    def generate_mapping(self, file_id: str) -> dict:
        uploaded_file = self.repo.get_uploaded_file(file_id)
        if not uploaded_file:
            raise Exception("File ID not found")

        incoming_columns = self.get_incoming_columns(uploaded_file["minio_path"])
        if not incoming_columns:
            raise Exception(f"Tidak ada kolom yang terbaca dari file {file_id}")

        user_prompt = USER_PROMPT_TEMPLATE.format(
            master_columns="\n".join(f"- {c}" for c in MASTER_MATCHING_COLUMNS),
            incoming_columns="\n".join(f"- {c}" for c in incoming_columns),
        )

        result: FieldMappingOutput = self.llm.invoke([
            SystemMessage(SYSTEM_PROMPT),
            HumanMessage(user_prompt),
        ])

        cleaned_pairs = self._validate_pairs(result.pairs, incoming_columns)

        # Regenerate-safe: matikan pairing GENAI lama sebelum insert yang baru.
        # Pairing yang sudah di-edit user (USER_EDITED) sengaja tidak disentuh.
        self.repo.deactivate_existing_mapping(file_id, source="GENAI")

        rows = [{**pair, "file_id": file_id} for pair in cleaned_pairs]
        self.repo.insert_mapping_rows(rows)

        # Regenerate membatalkan konfirmasi weight sebelumnya (kalau ada) —
        # pairing/weight lama belum tentu masih relevan dengan pairing baru.
        self.repo.set_is_custom_ready(file_id, False)

        return {
            "file_id": file_id,
            "incoming_columns_count": len(incoming_columns),
            "pairs_generated": len(cleaned_pairs),
            "pairs": cleaned_pairs,
        }

    def save_pairs(self, file_id: str, pairs: list[dict]) -> dict:
        """
        Step 7: user mengonfirmasi pairing final + weight lewat
        PUT /custom-mapping/{file_id}. Submission ini dianggap PENGGANTI PENUH
        dari active set sebelumnya (baik hasil GENAI maupun USER_EDITED lama).

        pairs: [{"master_column": str, "incoming_column": str, "weight": float}, ...]

        Raises:
            LookupError: file_id tidak ditemukan (-> 404 di routes.py)
            ValueError: validasi gagal — kolom gak valid, duplikat, total
                weight != 1.0, atau gak ada anchor blocking (-> 400 di routes.py)
        """
        uploaded_file = self.repo.get_uploaded_file(file_id)
        if not uploaded_file:
            raise LookupError("File ID not found")
        if uploaded_file["grade"] != 6:
            raise ValueError("File ini bukan grade 6 (custom) — tidak bisa disave sebagai custom mapping.")

        incoming_columns = set(self.get_incoming_columns(uploaded_file["minio_path"]))
        valid_master = set(MASTER_MATCHING_COLUMNS)

        if not pairs:
            raise ValueError("Minimal harus ada 1 pairing.")

        seen_master = set()
        seen_incoming = set()
        cleaned = []
        weight_sum = 0.0

        for pair in pairs:
            master_col = pair["master_column"]
            incoming_col = pair["incoming_column"]
            weight = pair["weight"]

            if master_col not in valid_master:
                raise ValueError(f"master_column tidak valid: {master_col}")
            if incoming_col not in incoming_columns:
                raise ValueError(f"incoming_column tidak ditemukan di file: {incoming_col}")
            if master_col in seen_master:
                raise ValueError(f"master_column dipakai lebih dari sekali: {master_col}")
            if incoming_col in seen_incoming:
                raise ValueError(f"incoming_column dipakai lebih dari sekali: {incoming_col}")

            seen_master.add(master_col)
            seen_incoming.add(incoming_col)

            # nik cuma blocking key (tidak pernah di-score, lihat
            # ScoringService.compute_dynamic_similarity_score), jadi weight-nya
            # sengaja TIDAK ikut dihitung ke total yang harus = 1.0.
            if master_col != "nik":
                weight_sum += weight

            cleaned.append({
                "file_id": file_id,
                "master_column": master_col,
                "incoming_column": incoming_col,
                "weight": weight,
                "confidence": None,
                "source": "USER_EDITED",
            })

        if abs(weight_sum - 1.0) > 0.001:
            raise ValueError(
                f"Total weight (di luar nik) harus = 1.0, saat ini = {round(weight_sum, 4)}"
            )

        blocking_capable_fields = {"nik", *BLOCKING_ANCHOR_FIELDS}
        if not (seen_master & blocking_capable_fields):
            raise ValueError(
                "Pairing butuh minimal 1 dari: nik, jenis_kelamin, nama_lengkap, "
                "atau tanggal_lahir, supaya matching punya blocking key yang aman "
                "(mencegah full cross join yang mahal)."
            )

        self.repo.deactivate_all_active(file_id)
        self.repo.insert_mapping_rows(cleaned)
        self.repo.set_is_custom_ready(file_id, True)

        return {
            "file_id": file_id,
            "pairs_saved": len(cleaned),
            "is_custom_ready": True,
        }