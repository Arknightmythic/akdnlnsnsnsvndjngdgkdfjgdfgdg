import os
import re
import time
from datetime import date, datetime
from dotenv import load_dotenv

from sqlalchemy import text
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from .schema import ReasoningOutput
from .prompt import SYSTEM_PROMPT
from .pattern_detector import PatternDetector

load_dotenv()


class ReasoningService:
    """
    Service utama untuk Reasoning AI.

    Sumber data : tabel `manual_matches` (driver utama) + `master` (untuk data pembanding)
    Tabel yang DITULIS : `manual_matches` dan `reasoning_patterns` SAJA.
    Tabel lain (institution, uploaded_files, dll) hanya dibaca untuk JOIN / referensi.
    """

    def __init__(self, engine):
        self.engine = engine
        self.pattern_detector = PatternDetector()

        llm_provider = os.getenv("LLM_PROVIDER", "ollama").lower()
        openai_base_url = os.getenv("MODEL_BASE_URL", "http://localhost:port")
        if not openai_base_url.endswith("/v1"):
            openai_base_url = openai_base_url.rstrip("/") + "/v1"

        if llm_provider == "vllm":
            vllm_model_name = os.getenv("VLLM_MODEL_NAME", "meta-llama/Meta-Llama-3-8B-Instruct")
            self.llm = ChatOpenAI(
                model=vllm_model_name,
                temperature=0.1,
                base_url=openai_base_url,
                api_key=os.getenv("OPENAI_API_KEY", "EMPTY"),
                max_tokens=500,
            ).with_structured_output(ReasoningOutput)
        else:
            self.llm = ChatOpenAI(
                model=os.getenv("OLLAMA_MODEL_NAME", "llama3.1:8b-instruct-q4_K_M"),
                temperature=0.1,
                base_url=openai_base_url,
                api_key=os.getenv("OPENAI_API_KEY", "ollama"),
            ).with_structured_output(ReasoningOutput)

        self.system_prompt = SYSTEM_PROMPT

    # ─────────────────────────────────────────────
    # Utility
    # ─────────────────────────────────────────────

    def _format_date(self, d):
        return d.strftime("%d-%m-%Y") if isinstance(d, date) else "null"

    # ─────────────────────────────────────────────
    # Cache (reasoning_patterns)
    # ─────────────────────────────────────────────

    def _get_cached_pattern(self, pattern_hash: str):
        query = text(
            "SELECT pattern_name, reason_template, hit_count "
            "FROM reasoning_patterns WHERE pattern_hash = :hash"
        )
        with self.engine.connect() as conn:
            return conn.execute(query, {"hash": pattern_hash}).mappings().first()

    def _save_pattern(
        self,
        pattern_hash: str,
        pattern_name_suffix: str,
        signature: str,
        template: str,
        sample_id: int,
    ) -> str:
        with self.engine.begin() as conn:
            count_res = conn.execute(
                text("SELECT COUNT(*) as c FROM reasoning_patterns")
            ).mappings().first()
            count = count_res["c"] if count_res else 0
            pattern_name = f"P{count + 1:03d}_{pattern_name_suffix}"

            try:
                conn.execute(
                    text(
                        "INSERT INTO reasoning_patterns "
                        "(pattern_hash, pattern_name, pattern_signature, reason_template, "
                        " sample_id, hit_count, created_at, updated_at) "
                        "VALUES (:hash, :name, :sig, :tpl, :sid, 1, :now, :now)"
                    ),
                    {
                        "hash": pattern_hash,
                        "name": pattern_name,
                        "sig": signature,
                        "tpl": template,
                        "sid": sample_id,
                        "now": datetime.now(),
                    },
                )
            except Exception as exc:
                print(f"[WARN] Failed to save pattern {pattern_hash}: {exc}")
        return pattern_name

    def _increment_pattern_hit(self, pattern_hash: str):
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE reasoning_patterns "
                    "SET hit_count = hit_count + 1, updated_at = :now "
                    "WHERE pattern_hash = :hash"
                ),
                {"hash": pattern_hash, "now": datetime.now()},
            )

    # ─────────────────────────────────────────────
    # Template helpers
    # ─────────────────────────────────────────────

    def _convert_to_template(self, reason: str, row: dict) -> str:
        """Ganti nilai aktual dalam reason dengan placeholder agar bisa di-cache."""
        tpl = reason

        def replace_ci(t, search, placeholder):
            if not search or str(search).strip().lower() in {"null", "none", "", "kosong"}:
                return t
            return re.sub(re.escape(str(search)), placeholder, t, flags=re.IGNORECASE)

        tpl = replace_ci(tpl, row.get("nama_lengkap"), "{incoming.nama_lengkap}")
        tpl = replace_ci(tpl, row.get("master_nama_lengkap"), "{master.nama_lengkap}")
        tpl = replace_ci(tpl, row.get("tempat_lahir"), "{incoming.tempat_lahir}")
        tpl = replace_ci(tpl, row.get("master_tempat_lahir"), "{master.tempat_lahir}")

        tgl_in = self._format_date(row.get("tanggal_lahir"))
        tgl_ms = self._format_date(row.get("master_tanggal_lahir"))
        if tgl_in and tgl_in != "null":
            tpl = re.sub(re.escape(tgl_in), "{incoming.tanggal_lahir}", tpl, flags=re.IGNORECASE)
        if tgl_ms and tgl_ms != "null":
            tpl = re.sub(re.escape(tgl_ms), "{master.tanggal_lahir}", tpl, flags=re.IGNORECASE)

        tpl = replace_ci(tpl, row.get("nama_ibu"), "{incoming.nama_ibu}")
        tpl = replace_ci(tpl, row.get("master_nama_ibu"), "{master.nama_ibu}")
        return tpl

    def _fill_template(self, template: str, row: dict) -> str:
        """Isi placeholder template dengan nilai aktual dari row."""
        r = template
        
        def _fmt_fill(val):
            v = str(val).strip()
            return "KOSONG" if v.lower() in {"none", "null", "nan", ""} else v
            
        r = r.replace("{incoming.nama_lengkap}", _fmt_fill(row.get("nama_lengkap")))
        r = r.replace("{master.nama_lengkap}", _fmt_fill(row.get("master_nama_lengkap")))
        r = r.replace("{incoming.tempat_lahir}", _fmt_fill(row.get("tempat_lahir")))
        r = r.replace("{master.tempat_lahir}", _fmt_fill(row.get("master_tempat_lahir")))
        r = r.replace("{incoming.tanggal_lahir}", _fmt_fill(self._format_date(row.get("tanggal_lahir"))))
        r = r.replace("{master.tanggal_lahir}", _fmt_fill(self._format_date(row.get("master_tanggal_lahir"))))
        r = r.replace("{incoming.nama_ibu}", _fmt_fill(row.get("nama_ibu")))
        r = r.replace("{master.nama_ibu}", _fmt_fill(row.get("master_nama_ibu")))
        return r

    # ─────────────────────────────────────────────
    # Data Fetching — HANYA READ
    # ─────────────────────────────────────────────

    def build_comparison_pairs(self, file_id: str, limit: int = None) -> tuple:
        """
        Ambil semua baris dari manual_matches yang belum diproses,
        di-JOIN dengan master untuk mendapatkan data pembanding.

        Join Strategy (handle semua grade):
        - Grade A/B : nik_incoming berisi NIK → JOIN master ON nik
        - Grade C/D : nik_incoming mungkin NULL/kosong, sehingga join via institution.nik_master

        Kedua jalur digabungkan dengan UNION sehingga semua grade terlayani.
        """
        query_str = """
            SELECT
                mm.id              AS id,
                mm.file_id         AS file_id,
                mm.id_incoming     AS id_incoming,
                mm.nik_incoming    AS nik_incoming,
                mm.nama_incoming            AS nama_lengkap,
                mm.tempat_lahir_incoming    AS tempat_lahir,
                mm.tanggal_lahir_incoming   AS tanggal_lahir,
                mm.jenis_kelamin_incoming   AS jenis_kelamin,
                mm.nama_ibu_incoming        AS nama_ibu,
                m.nama_lengkap              AS master_nama_lengkap,
                m.tempat_lahir              AS master_tempat_lahir,
                m.tanggal_lahir             AS master_tanggal_lahir,
                m.jenis_kelamin             AS master_jenis_kelamin,
                m.nama_ibu                  AS master_nama_ibu
            FROM manual_matches mm
            -- Grade A/B: nik_incoming langsung ke master.nik
            JOIN master m ON mm.nik_incoming = m.nik
            WHERE mm.file_id = :file_id
              AND mm.reasoning_status IN ('PENDING', 'FAILED')

            UNION ALL

            SELECT
                mm.id              AS id,
                mm.file_id         AS file_id,
                mm.id_incoming     AS id_incoming,
                mm.nik_incoming    AS nik_incoming,
                mm.nama_incoming            AS nama_lengkap,
                mm.tempat_lahir_incoming    AS tempat_lahir,
                mm.tanggal_lahir_incoming   AS tanggal_lahir,
                mm.jenis_kelamin_incoming   AS jenis_kelamin,
                mm.nama_ibu_incoming        AS nama_ibu,
                m.nama_lengkap              AS master_nama_lengkap,
                m.tempat_lahir              AS master_tempat_lahir,
                m.tanggal_lahir             AS master_tanggal_lahir,
                m.jenis_kelamin             AS master_jenis_kelamin,
                m.nama_ibu                  AS master_nama_ibu
            FROM manual_matches mm
            -- Grade C/D: nik_incoming NULL/kosong → join via institution.nik_master
            JOIN institution inst
                ON inst.file_id = mm.file_id
               AND inst.id_incoming = mm.id_incoming
            JOIN master m ON inst.nik_master = m.nik
            WHERE mm.file_id = :file_id
              AND mm.reasoning_status IN ('PENDING', 'FAILED')
              AND (mm.nik_incoming IS NULL OR mm.nik_incoming = '')
        """
        if limit is not None:
            query_str += f" LIMIT {limit}"

        with self.engine.connect() as conn:
            rows = conn.execute(text(query_str), {"file_id": file_id}).mappings().all()

        if not rows:
            return None, "No pending records found in manual_matches for this file_id"

        # De-duplicate berdasarkan mm.id (UNION bisa menghasilkan duplikat jika row cocok di keduanya)
        seen = set()
        unique_rows = []
        for row in rows:
            if row["id"] not in seen:
                seen.add(row["id"])
                unique_rows.append(dict(row))

        return unique_rows, None

    def build_comparison_pair_by_id(self, mm_id: int) -> tuple:
        """
        Ambil satu baris dari manual_matches berdasarkan id,
        di-JOIN dengan master untuk mendapatkan data pembanding.
        """
        query_str = """
            SELECT
                mm.id              AS id,
                mm.file_id         AS file_id,
                mm.id_incoming     AS id_incoming,
                mm.nik_incoming    AS nik_incoming,
                mm.nama_incoming            AS nama_lengkap,
                mm.tempat_lahir_incoming    AS tempat_lahir,
                mm.tanggal_lahir_incoming   AS tanggal_lahir,
                mm.jenis_kelamin_incoming   AS jenis_kelamin,
                mm.nama_ibu_incoming        AS nama_ibu,
                m.nama_lengkap              AS master_nama_lengkap,
                m.tempat_lahir              AS master_tempat_lahir,
                m.tanggal_lahir             AS master_tanggal_lahir,
                m.jenis_kelamin             AS master_jenis_kelamin,
                m.nama_ibu                  AS master_nama_ibu
            FROM manual_matches mm
            JOIN master m ON mm.nik_incoming = m.nik
            WHERE mm.id = :mm_id

            UNION ALL

            SELECT
                mm.id              AS id,
                mm.file_id         AS file_id,
                mm.id_incoming     AS id_incoming,
                mm.nik_incoming    AS nik_incoming,
                mm.nama_incoming            AS nama_lengkap,
                mm.tempat_lahir_incoming    AS tempat_lahir,
                mm.tanggal_lahir_incoming   AS tanggal_lahir,
                mm.jenis_kelamin_incoming   AS jenis_kelamin,
                mm.nama_ibu_incoming        AS nama_ibu,
                m.nama_lengkap              AS master_nama_lengkap,
                m.tempat_lahir              AS master_tempat_lahir,
                m.tanggal_lahir             AS master_tanggal_lahir,
                m.jenis_kelamin             AS master_jenis_kelamin,
                m.nama_ibu                  AS master_nama_ibu
            FROM manual_matches mm
            JOIN institution inst
                ON inst.file_id = mm.file_id
               AND inst.id_incoming = mm.id_incoming
            JOIN master m ON inst.nik_master = m.nik
            WHERE mm.id = :mm_id
              AND (mm.nik_incoming IS NULL OR mm.nik_incoming = '')
        """
        with self.engine.connect() as conn:
            row = conn.execute(text(query_str), {"mm_id": mm_id}).mappings().first()

        if not row:
            return None, f"No joinable record found for manual_matches id: {mm_id}"

        return dict(row), None

    # ─────────────────────────────────────────────
    # Main Processing
    # ─────────────────────────────────────────────

    def _update_mm_status(self, mm_id: int, status: str):
        """Update reasoning_status di manual_matches."""
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE manual_matches SET reasoning_status = :status WHERE id = :id"
                ),
                {"status": status, "id": mm_id},
            )

    def _update_mm_result(self, mm_id: int, reason: str, pattern_name: str, source: str):
        """Tulis hasil reasoning ke manual_matches."""
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE manual_matches "
                    "SET reason = :reason, pattern_name = :pname, "
                    "    reasoning_source = :source, reasoning_status = 'COMPLETED' "
                    "WHERE id = :id"
                ),
                {"reason": reason, "pname": pattern_name, "source": source, "id": mm_id},
            )

    def process_reasoning(self, file_id: str, dry_run: bool = False, limit: int = None):
        start_total = time.perf_counter()

        fetch_start = time.perf_counter()
        rows, err = self.build_comparison_pairs(file_id, limit=limit)
        fetch_duration = time.perf_counter() - fetch_start

        if err:
            return {"status": "error", "message": err}

        results = []
        updated_count = 0
        total_rows = len(rows)

        for idx, row in enumerate(rows):
            mm_id = int(row["id"])
            start_row = time.perf_counter()

            # Tandai sedang diproses (agar worker lain tidak dobel proses)
            if not dry_run:
                self._update_mm_status(mm_id, "PROCESSING")

            pattern_info = self.pattern_detector.detect(row)
            pattern_hash = pattern_info["pattern_hash"]

            cached = self._get_cached_pattern(pattern_hash) if not dry_run else None
            llm_duration = 0.0

            try:
                if cached:
                    # ── CACHE HIT ──
                    reason_text = self._fill_template(cached["reason_template"], row)
                    pattern_name = cached["pattern_name"]
                    source = "CACHE"

                    if not dry_run:
                        self._increment_pattern_hit(pattern_hash)
                        self._update_mm_result(mm_id, reason_text, pattern_name, source)
                        updated_count += 1

                    print(
                        f"Row {idx+1}/{total_rows} | ID: {mm_id} "
                        f"| [CACHE HIT] {pattern_name} | {reason_text}"
                    )

                else:
                    # ── CACHE MISS → LLM ──
                    def _fmt(val):
                        v = str(val).strip()
                        return "KOSONG" if v.lower() in {"none", "null", "nan", ""} else v

                    human_prompt = f"ID: {mm_id}\n\nInstitution (Incoming):\n"
                    human_prompt += f"  Nama Lengkap   : {_fmt(row['nama_lengkap'])}\n"
                    human_prompt += f"  Tempat Lahir   : {_fmt(row['tempat_lahir'])}\n"
                    human_prompt += f"  Tanggal Lahir  : {_fmt(self._format_date(row['tanggal_lahir']))}\n"
                    human_prompt += f"  Jenis Kelamin  : {_fmt(row['jenis_kelamin'])}\n"
                    human_prompt += f"  Nama Ibu       : {_fmt(row['nama_ibu'])}\n\n"
                    human_prompt += "Master:\n"
                    human_prompt += f"  Nama Lengkap   : {_fmt(row['master_nama_lengkap'])}\n"
                    human_prompt += f"  Tempat Lahir   : {_fmt(row['master_tempat_lahir'])}\n"
                    human_prompt += f"  Tanggal Lahir  : {_fmt(self._format_date(row['master_tanggal_lahir']))}\n"
                    human_prompt += f"  Jenis Kelamin  : {_fmt(row['master_jenis_kelamin'])}\n"
                    human_prompt += f"  Nama Ibu       : {_fmt(row['master_nama_ibu'])}\n"

                    messages = [
                        SystemMessage(content=self.system_prompt.strip()),
                        HumanMessage(content=human_prompt.strip()),
                    ]

                    llm_start = time.perf_counter()
                    response = self.llm.invoke(messages)
                    llm_duration = time.perf_counter() - llm_start

                    reason_text = response.reason
                    source = "LLM"

                    if not dry_run:
                        template = self._convert_to_template(reason_text, row)
                        pattern_name = self._save_pattern(
                            pattern_hash,
                            pattern_info["pattern_name_suffix"],
                            pattern_info["pattern_signature"],
                            template,
                            mm_id,
                        )
                        self._update_mm_result(mm_id, reason_text, pattern_name, source)
                        updated_count += 1
                    else:
                        pattern_name = f"DRY_RUN_{pattern_info['pattern_name_suffix']}"

                    print(
                        f"Row {idx+1}/{total_rows} | ID: {mm_id} "
                        f"| [LLM {round(llm_duration, 2)}s] {pattern_name} | {reason_text}"
                    )

            except Exception as exc:
                print(f"[ERR] Error processing manual_matches ID {mm_id}: {exc}")
                if not dry_run:
                    self._update_mm_status(mm_id, "FAILED")
                results.append({"id": mm_id, "error": str(exc)})
                continue

            row_duration = time.perf_counter() - start_row
            results.append(
                {
                    "id": mm_id,
                    "reason": reason_text,
                    "pattern_name": pattern_name,
                    "source": source,
                    "llm_time_seconds": round(llm_duration, 2),
                    "total_time_seconds": round(row_duration, 2),
                }
            )

        total_duration = time.perf_counter() - start_total
        return {
            "file_id": file_id,
            "dry_run": dry_run,
            "processed_count": total_rows,
            "updated_count": updated_count,
            "data_fetch_time_seconds": round(fetch_duration, 2),
            "total_time_seconds": round(total_duration, 2),
            "results": results,
        }

    def process_reasoning_by_id(self, mm_id: int, dry_run: bool = False, commit_to_db: bool = True):
        """Memproses AI reasoning untuk 1 baris spesifik (id dari manual_matches)."""
        start_row = time.perf_counter()

        row, err = self.build_comparison_pair_by_id(mm_id)
        if err:
            if not dry_run and commit_to_db:
                self._update_mm_status(mm_id, "FAILED")
            return {"status": "error", "message": err, "id": mm_id}

        if not dry_run and commit_to_db:
            self._update_mm_status(mm_id, "PROCESSING")

        pattern_info = self.pattern_detector.detect(row)
        pattern_hash = pattern_info["pattern_hash"]

        cached = self._get_cached_pattern(pattern_hash) if not dry_run else None
        llm_duration = 0.0

        try:
            if cached:
                # ── CACHE HIT ──
                reason_text = self._fill_template(cached["reason_template"], row)
                pattern_name = cached["pattern_name"]
                source = "CACHE"

                if not dry_run:
                    if commit_to_db: # <--- Mencegah penulisan satuan jika sedang mode Batching
                        self._increment_pattern_hit(pattern_hash)
                        self._update_mm_result(mm_id, reason_text, pattern_name, source)

                print(f"[ID: {mm_id}] [CACHE HIT] {pattern_name} | {reason_text}")

            else:
                # ── CACHE MISS → LLM ──
                def _fmt(val):
                    v = str(val).strip()
                    return "KOSONG" if v.lower() in {"none", "null", "nan", ""} else v

                human_prompt = f"ID: {mm_id}\n\nInstitution (Incoming):\n"
                human_prompt += f"  Nama Lengkap   : {_fmt(row['nama_lengkap'])}\n"
                human_prompt += f"  Tempat Lahir   : {_fmt(row['tempat_lahir'])}\n"
                human_prompt += f"  Tanggal Lahir  : {_fmt(self._format_date(row['tanggal_lahir']))}\n"
                human_prompt += f"  Jenis Kelamin  : {_fmt(row['jenis_kelamin'])}\n"
                human_prompt += f"  Nama Ibu       : {_fmt(row['nama_ibu'])}\n\n"
                human_prompt += "Master:\n"
                human_prompt += f"  Nama Lengkap   : {_fmt(row['master_nama_lengkap'])}\n"
                human_prompt += f"  Tempat Lahir   : {_fmt(row['master_tempat_lahir'])}\n"
                human_prompt += f"  Tanggal Lahir  : {_fmt(self._format_date(row['master_tanggal_lahir']))}\n"
                human_prompt += f"  Jenis Kelamin  : {_fmt(row['master_jenis_kelamin'])}\n"
                human_prompt += f"  Nama Ibu       : {_fmt(row['master_nama_ibu'])}\n"

                messages = [
                    SystemMessage(content=self.system_prompt.strip()),
                    HumanMessage(content=human_prompt.strip()),
                ]

                llm_start = time.perf_counter()
                response = self.llm.invoke(messages)
                llm_duration = time.perf_counter() - llm_start

                reason_text = response.reason
                source = "LLM"

                if not dry_run:
                    template = self._convert_to_template(reason_text, row)
                    # save_pattern tetap dieksekusi langsung agar pattern baru langsung terekam
                    pattern_name = self._save_pattern(
                        pattern_hash,
                        pattern_info["pattern_name_suffix"],
                        pattern_info["pattern_signature"],
                        template,
                        mm_id,
                    )
                    
                    if commit_to_db: # <--- Mencegah penulisan satuan
                        self._update_mm_result(mm_id, reason_text, pattern_name, source)
                else:
                    pattern_name = f"DRY_RUN_{pattern_info['pattern_name_suffix']}"

                print(f"[ID: {mm_id}] [LLM {round(llm_duration, 2)}s] {pattern_name} | {reason_text}")

        except Exception as exc:
            print(f"[ERR] Error processing manual_matches ID {mm_id}: {exc}")
            if not dry_run and commit_to_db:
                self._update_mm_status(mm_id, "FAILED")
            return {"status": "error", "message": str(exc), "id": mm_id}

        row_duration = time.perf_counter() - start_row
        return {
            "status": "success",
            "id": mm_id,
            "reason": reason_text,
            "pattern_name": pattern_name,
            "source": source,
            "llm_time_seconds": round(llm_duration, 2),
            "total_time_seconds": round(row_duration, 2),
        }
    
    def bulk_update_mm_results(self, results: list):
        """
        True Bulk Upsert menggunakan fitur Partial Update StarRocks.
        Kode super bersih tanpa perlu merakit string SQL secara manual!
        """
        from sqlalchemy import text
        
        success_data = []
        error_data = []
        
        for r in results:
            if r["status"] == "success":
                success_data.append({
                    "p_id": r["id"],
                    "p_reason": r["reason"],
                    "p_pattern": r["pattern_name"],
                    "p_source": r["source"],
                    "p_status": "COMPLETED"
                })
            else:
                error_data.append({
                    "p_id": r["id"],
                    "p_status": "FAILED"
                })

        with self.engine.begin() as conn:
            try:
                # 1. PERBAIKAN: Gunakan variabel 'enable_insert_partial_update' sesuai versi StarRocks Anda
                conn.execute(text("SET enable_insert_partial_update=true;"))
                
                # 2. Eksekusi INSERT 
                if success_data:
                    conn.execute(text("""
                        INSERT INTO manual_matches (id, reason, pattern_name, reasoning_source, reasoning_status)
                        VALUES (:p_id, :p_reason, :p_pattern, :p_source, :p_status)
                    """), success_data)
                    
                if error_data:
                    conn.execute(text("""
                        INSERT INTO manual_matches (id, reasoning_status)
                        VALUES (:p_id, :p_status)
                    """), error_data)
                    
            finally:
                # 3. PERBAIKAN: Pastikan dikembalikan ke false menggunakan nama variabel yang sama
                conn.execute(text("SET enable_insert_partial_update=false;"))
                
        print(f"[Bulk Update] Menyimpan {len(success_data)} sukses & {len(error_data)} gagal menggunakan metode UPSERT.")