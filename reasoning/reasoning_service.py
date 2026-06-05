import os
import json
import re
import time
from datetime import date, datetime
from dotenv import load_dotenv

import duckdb
import polars as pl
from sqlalchemy import text
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from .schema import ReasoningOutput

from processing.matching_service import MatchingService
from .prompt import SYSTEM_PROMPT
from .pattern_detector import PatternDetector

load_dotenv()

class ReasoningService:
    def __init__(self, engine, minio_client, bucket_name):
        self.engine = engine
        self.matching_service = MatchingService(engine, minio_client, bucket_name)
        self.pattern_detector = PatternDetector()
        
        # Ambil konfigurasi dari .env
        openai_base_url = os.getenv("MODEL_BASE_URL", "http://localhost:port")
        if not openai_base_url.endswith("/v1"):
            openai_base_url = openai_base_url.rstrip("/") + "/v1"
            
        openai_api_key = os.getenv("OPENAI_API_KEY", "ollama")
        
        self.llm = ChatOpenAI(
            model="llama3.1:8b-instruct-q4_K_M",
            temperature=0.1,
            base_url=openai_base_url,
            api_key=openai_api_key
        ).with_structured_output(ReasoningOutput)

        self.system_prompt = SYSTEM_PROMPT

    def _format_date(self, d):
        return d.strftime("%d-%m-%Y") if isinstance(d, date) else "null"

    def _get_cached_pattern(self, pattern_hash: str):
        query = text("SELECT pattern_name, reason_template, hit_count FROM reasoning_patterns WHERE pattern_hash = :hash")
        with self.engine.connect() as conn:
            return conn.execute(query, {"hash": pattern_hash}).mappings().first()

    def _save_pattern(self, pattern_hash: str, pattern_name_suffix: str, signature: str, template: str, sample_id: int):
        with self.engine.begin() as conn:
            count_res = conn.execute(text("SELECT COUNT(*) as c FROM reasoning_patterns")).mappings().first()
            count = count_res['c'] if count_res else 0
            
            pattern_name = f"P{count+1:03d}_{pattern_name_suffix}"
            
            query = text("""
                INSERT INTO reasoning_patterns 
                (pattern_hash, pattern_name, pattern_signature, reason_template, sample_id, hit_count, created_at, updated_at)
                VALUES (:hash, :name, :sig, :tpl, :sid, 1, :now, :now)
            """)
            try:
                conn.execute(query, {
                    "hash": pattern_hash,
                    "name": pattern_name,
                    "sig": signature,
                    "tpl": template,
                    "sid": sample_id,
                    "now": datetime.utcnow()
                })
            except Exception as e:
                print(f"Failed to save pattern {pattern_hash}: {e}")
            return pattern_name

    def _increment_pattern_hit(self, pattern_hash: str):
        query = text("""
            UPDATE reasoning_patterns 
            SET hit_count = hit_count + 1, updated_at = :now
            WHERE pattern_hash = :hash
        """)
        with self.engine.begin() as conn:
            conn.execute(query, {"hash": pattern_hash, "now": datetime.utcnow()})

    def _convert_to_template(self, reason: str, row: dict) -> str:
        template = reason
        
        def replace_ci(tpl, search_str, replacement_str):
            if not search_str or str(search_str).strip().lower() in ["null", "none", "", "kosong"]:
                return tpl
            return re.sub(re.escape(str(search_str)), replacement_str, tpl, flags=re.IGNORECASE)

        template = replace_ci(template, row.get("nama_lengkap"), "{incoming.nama_lengkap}")
        template = replace_ci(template, row.get("master_nama_lengkap"), "{master.nama_lengkap}")
        
        template = replace_ci(template, row.get("tempat_lahir"), "{incoming.tempat_lahir}")
        template = replace_ci(template, row.get("master_tempat_lahir"), "{master.tempat_lahir}")
            
        tgl_in = self._format_date(row.get("tanggal_lahir"))
        tgl_ms = self._format_date(row.get("master_tanggal_lahir"))
        if tgl_in and tgl_in != "null":
            template = re.sub(re.escape(tgl_in), "{incoming.tanggal_lahir}", template, flags=re.IGNORECASE)
        if tgl_ms and tgl_ms != "null":
            template = re.sub(re.escape(tgl_ms), "{master.tanggal_lahir}", template, flags=re.IGNORECASE)
            
        template = replace_ci(template, row.get("nama_ibu"), "{incoming.nama_ibu}")
        template = replace_ci(template, row.get("master_nama_ibu"), "{master.nama_ibu}")

        return template

    def _fill_template(self, template: str, row: dict) -> str:
        reason = template
        reason = reason.replace("{incoming.nama_lengkap}", str(row.get("nama_lengkap") or "null"))
        reason = reason.replace("{master.nama_lengkap}", str(row.get("master_nama_lengkap") or "null"))
        
        reason = reason.replace("{incoming.tempat_lahir}", str(row.get("tempat_lahir") or "null"))
        reason = reason.replace("{master.tempat_lahir}", str(row.get("master_tempat_lahir") or "null"))
        
        reason = reason.replace("{incoming.tanggal_lahir}", self._format_date(row.get("tanggal_lahir")))
        reason = reason.replace("{master.tanggal_lahir}", self._format_date(row.get("master_tanggal_lahir")))
        
        reason = reason.replace("{incoming.nama_ibu}", str(row.get("nama_ibu") or "null"))
        reason = reason.replace("{master.nama_ibu}", str(row.get("master_nama_ibu") or "null"))
        
        return reason

    def get_manual_review_rows(self, file_id: str, limit: int = None):
        query_str = """
            SELECT 
                id,
                id_incoming as nik_incoming,
                nik_master
            FROM institution
            WHERE file_id = :file_id 
              AND match_result = 2
              AND reasoning_source IS NULL
            ORDER BY inserted_date DESC
        """
        if limit is not None:
            query_str += f" LIMIT {limit}"
            
        query = text(query_str)
        
        with self.engine.connect() as conn:
            return conn.execute(query, {"file_id": file_id}).mappings().all()

    def build_comparison_pairs(self, file_id: str, limit: int = None):
        institution_rows = self.get_manual_review_rows(file_id, limit=limit)
        if not institution_rows:
            return None, "No MANUAL_REVIEW records found in institution table or all already processed"
            
        uploaded_file = self.matching_service.get_uploaded_file(file_id)
        if not uploaded_file:
            return None, f"No uploaded_files record found for file_id={file_id}"
            
        incoming_df = self.matching_service.load_parquet_from_minio(uploaded_file["minio_path"])
        master_df = self.matching_service.fetch_master_dataset()
        inst_df = pl.DataFrame([dict(row) for row in institution_rows])
        
        # Normalisasi grade karena skema DB diupdate menjadi foreign key integer
        grade_val = str(uploaded_file.get("grade", "")).strip().upper()
        grade_map = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}
        grade = grade_map.get(grade_val, grade_val)
        
        con = duckdb.connect()
        con.register("incoming_df", incoming_df.to_arrow())
        con.register("master_df", master_df.to_arrow())
        con.register("inst_df", inst_df.to_arrow())
        
        # Grade C dan D tidak punya NIK, jadi nik_incoming di tabel institution sebenarnya adalah id dari parquet
        incoming_join_col = "id" if grade in ["C", "D"] else "nik"
        
        joined_df = con.execute(f"""
            SELECT 
                inst.id,
                i.nama_clean AS nama_lengkap,
                i.tempat_lahir_clean AS tempat_lahir,
                i.tanggal_lahir_clean AS tanggal_lahir,
                i.jenis_kelamin_clean AS jenis_kelamin,
                i.nama_ibu_clean AS nama_ibu,
                m.nama_master_clean AS master_nama_lengkap,
                m.tempat_lahir_master_clean AS master_tempat_lahir,
                m.tanggal_lahir_master_clean AS master_tanggal_lahir,
                m.jenis_kelamin_master_clean AS master_jenis_kelamin,
                m.nama_ibu_master_clean AS master_nama_ibu
            FROM inst_df inst
            JOIN incoming_df i ON inst.nik_incoming = i.{incoming_join_col}
            JOIN master_df m ON inst.nik_master = m.nik
        """).pl()
        
        if joined_df.height == 0:
            return None, "Joined dataframe is empty"
            
        return joined_df, None

    def process_reasoning(self, file_id: str, dry_run: bool = False, limit: int = None):
        start_time_total = time.perf_counter()
        
        fetch_start = time.perf_counter()
        joined_df, err = self.build_comparison_pairs(file_id, limit=limit)
        fetch_duration = time.perf_counter() - fetch_start
        
        if err:
            return {"status": "error", "message": err}
            
        results = []
        updated_count = 0
        total_rows = joined_df.height
        
        # Proses satu per satu
        for idx, row in enumerate(joined_df.iter_rows(named=True)):
            if limit is not None and idx >= limit:
                break
                
            start_time_row = time.perf_counter()
            pivot_id = int(row["id"])
            
            # Detect pattern caching
            pattern_info = self.pattern_detector.detect(row)
            pattern_hash = pattern_info["pattern_hash"]
            
            cached = self._get_cached_pattern(pattern_hash) if not dry_run else None
            
            if cached:
                # CACHE HIT
                reason_text = self._fill_template(cached["reason_template"], row)
                pattern_name = cached["pattern_name"]
                source = "CACHE"
                llm_duration = 0.0
                
                if not dry_run:
                    self._increment_pattern_hit(pattern_hash)
                    with self.engine.begin() as conn:
                        conn.execute(
                            text("""
                            UPDATE institution
                            SET reason = :reason, pattern_name = :pattern_name, reasoning_source = :source
                            WHERE id = :id
                            """),
                            {
                                "reason": reason_text, 
                                "pattern_name": pattern_name,
                                "source": source,
                                "id": pivot_id
                            }
                        )
                    updated_count += 1
                
                print(f"Row {idx+1}/{total_rows} | ID: {pivot_id} | [CACHE HIT] {pattern_name} | {reason_text}")

            else:
                def _fmt(val):
                    v = str(val).strip()
                    if v.lower() in ["none", "null", "nan", ""]:
                        return "KOSONG"
                    return v

                # CACHE MISS - Call LLM
                human_prompt = f"ID: {pivot_id}\n\nInstitution (Incoming):\n"
                human_prompt += f"  Nama Lengkap   : {_fmt(row['nama_lengkap'])}\n"
                human_prompt += f"  Tempat Lahir   : {_fmt(row['tempat_lahir'])}\n"
                human_prompt += f"  Tanggal Lahir  : {_fmt(self._format_date(row['tanggal_lahir']))}\n"
                human_prompt += f"  Jenis Kelamin  : {_fmt(row['jenis_kelamin'])}\n"
                human_prompt += f"  Nama Ibu       : {_fmt(row['nama_ibu'])}\n\n"
                human_prompt += f"Master:\n"
                human_prompt += f"  Nama Lengkap   : {_fmt(row['master_nama_lengkap'])}\n"
                human_prompt += f"  Tempat Lahir   : {_fmt(row['master_tempat_lahir'])}\n"
                human_prompt += f"  Tanggal Lahir  : {_fmt(self._format_date(row['master_tanggal_lahir']))}\n"
                human_prompt += f"  Jenis Kelamin  : {_fmt(row['master_jenis_kelamin'])}\n"
                human_prompt += f"  Nama Ibu       : {_fmt(row['master_nama_ibu'])}\n"

                messages = [
                    SystemMessage(content=self.system_prompt.strip()),
                    HumanMessage(content=human_prompt.strip())
                ]

                try:
                    llm_start = time.perf_counter()
                    response = self.llm.invoke(messages)
                    llm_duration = time.perf_counter() - llm_start
                    
                    reason_text = response.reason
                    
                    source = "LLM"
                    
                    if not dry_run:
                        # Convert to template and save pattern
                        template = self._convert_to_template(reason_text, row)
                        pattern_name = self._save_pattern(
                            pattern_hash, 
                            pattern_info["pattern_name_suffix"], 
                            pattern_info["pattern_signature"], 
                            template, 
                            pivot_id
                        )
                        
                        with self.engine.begin() as conn:
                            conn.execute(
                                text("""
                                UPDATE institution
                                SET reason = :reason, pattern_name = :pattern_name, reasoning_source = :source
                                WHERE id = :id
                                """),
                                {
                                    "reason": reason_text, 
                                    "pattern_name": pattern_name,
                                    "source": source,
                                    "id": pivot_id
                                }
                            )
                        updated_count += 1
                    else:
                        pattern_name = f"DRY_RUN_{pattern_info['pattern_name_suffix']}"
                    
                    print(f"Row {idx+1}/{total_rows} | ID: {pivot_id} | [LLM {round(llm_duration,2)}s] {pattern_name} | {reason_text}")

                except Exception as e:
                    print(f"Error processing row ID {pivot_id}: {e}")
                    results.append({"id": pivot_id, "error": str(e)})
                    continue

            row_duration = time.perf_counter() - start_time_row
            results.append({
                "id": pivot_id,
                "reason": reason_text,
                "pattern_name": pattern_name,
                "source": source,
                "llm_time_seconds": round(llm_duration, 2),
                "total_time_seconds": round(row_duration, 2)
            })

        total_duration = time.perf_counter() - start_time_total
        return {
            "file_id": file_id,
            "dry_run": dry_run,
            "processed_count": total_rows,
            "updated_count": updated_count,
            "data_fetch_time_seconds": round(fetch_duration, 2),
            "total_time_seconds": round(total_duration, 2),
            "results": results
        }
