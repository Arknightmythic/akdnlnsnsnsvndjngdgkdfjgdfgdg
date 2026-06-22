import time
import json
import duckdb
import polars as pl
import time
from sqlalchemy import text
from .string_similarity import ScoringService
from .minio_fetching_service import ObjectStorageService
from .repository import StarrocksService
from audit.audit_service import AuditService
from reasoning.tasks import trigger_rows_for_file
from retrieval.tasks import generate_export_csv


class MatchingServiceV2:
    def __init__(self, engine, minio_client, bucket_name, grade_rules):
        self.scoring_service = ScoringService()
        self.object_storage_service = ObjectStorageService(minio_client, bucket_name)
        self.starrocks_service = StarrocksService(engine)
        self.grade_rules = grade_rules
        self.audit_service = AuditService(engine)

        # ── Injected dari tasks.py setelah inisialisasi ────────────────────
        # redis dan file_id_ctx di-set oleh run_matching_task sebelum process_file
        # dipanggil. Default None agar tetap aman dipakai tanpa worker (unit test).
        self.redis = None
        self.file_id_ctx = None

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _log(self, message: str, level: str = "INFO"):
        """Push satu baris log ke Redis jika redis tersedia."""
        if self.redis is not None and self.file_id_ctx is not None:
            from processing.tasks import push_log
            push_log(self.redis, self.file_id_ctx, message, level)

    # ─── Core methods (tidak berubah kecuali penambahan _log) ─────────────────

    def get_matching_data(self, file_id, grade):
        uploaded_file = self.starrocks_service.get_uploaded_file(file_id)

        if not uploaded_file:
            raise Exception("File ID not found")

        if uploaded_file["grade"] != grade:
            raise Exception(
                f"This endpoint only processes Grade {grade} files"
            )

        incoming_df = self.object_storage_service.load_parquet_from_minio(
            uploaded_file["minio_path"]
        )
        self._log(f"Incoming rows: {incoming_df.height:,}")
        print(f"Incoming rows: {incoming_df.height}")

        master_df = self.starrocks_service.fetch_master_dataset()
        self._log(f"Master rows fetched: {master_df.height:,}")
        print(f"Master rows fetched: {master_df.height}")

        return uploaded_file, incoming_df, master_df

    def classify_result(self, grade_code: str, score: float, missing_count: int):
        rule = self.grade_rules[grade_code]

        auto_missing_max = rule["auto_missing_max"]
        auto_score_min = rule["auto_score_min"]
        review_missing_count = rule["review_missing_count"]
        review_score_min = rule["review_score_min"]
        review_score_max = rule["review_score_max"]

        auto_missing_ok = (
            auto_missing_max is None
            or missing_count <= auto_missing_max
        )

        if auto_missing_ok and score >= auto_score_min:
            return 1

        review_missing_ok = (
            review_missing_count is None
            or missing_count == review_missing_count
        )

        if (
            review_missing_ok
            and review_score_min <= score < review_score_max
        ):
            return 2

        return 3

    def trigger_ai_reasoning(self, file_id):
        try:
            trigger_rows_for_file.delay(file_id)
            self._log("Triggering AI reasoning...")
            print(f"Enqueued reasoning orchestrator for file {file_id}")
        except Exception as e:
            print(f"Failed to enqueue reasoning orchestrator for {file_id}: {e}")

    def partition_dataframe(self, df: pl.DataFrame, batch_size: int):
        total_rows = df.height

        for offset in range(0, total_rows, batch_size):
            yield df.slice(offset, batch_size)

    def count_missing_attributes(self, grade, row):
        if grade == 1 or grade == 3:
            return 0
        elif grade == 2:
            return sum([
                not row["nama_clean"],
                not row["tempat_lahir_clean"],
                not row["nama_ibu_clean"]
            ])
        elif grade == 4:
            return sum([
                not row["tanggal_lahir_clean"],
                not row["tempat_lahir_clean"],
                not row["nama_ibu_clean"]
            ])
        elif grade == 5:
            return sum([
                not row["nama_clean"],
                not row["tanggal_lahir_clean"],
                not any([
                    row["provinsi_clean"],
                    row["kabupaten_clean"],
                    row["kecamatan_clean"],
                    row["kelurahan_clean"]
                ]),
                not row["nama_ibu_clean"]
            ])

    def process_partition(self, uploaded_file, partition, master_df, file_id, grade):
        con = duckdb.connect()
        con.register("incoming_df", partition.to_arrow())
        con.register("master_df", master_df.to_arrow())

        joined_df = con.execute(self.starrocks_service.load_matching_query(grade)).pl()
        self._log(f"Joined rows: {joined_df.height:,}")
        print(f"Joined rows: {joined_df.height}")

        results_map = {}
        sync_status = 3
        all_incoming_ids = (partition.select("id").to_series().to_list())

        for row in joined_df.iter_rows(named=True):
            incoming_row_id = row["incoming_row_id"]
            if row["nik_master"] is None:
                results_map[incoming_row_id] = {
                    "score": 0,
                    "result": 3,
                    "nik_master": None
                }
                continue

            missing_count = self.count_missing_attributes(grade, row)

            nama_clean = row.get("nama_clean")
            nama_master_clean = row.get("nama_master_clean")
            tempat_lahir_clean = row.get("tempat_lahir_clean")
            tempat_lahir_master_clean = row.get("tempat_lahir_master_clean")
            tanggal_lahir_clean = row.get("tanggal_lahir_clean")
            tanggal_lahir_master_clean = row.get("tanggal_lahir_master_clean")
            nama_ibu_clean = row.get("nama_ibu_clean")
            nama_ibu_master_clean = row.get("nama_ibu_master_clean")
            provinsi_clean = row.get("provinsi_clean")
            provinsi_master_clean = row.get("provinsi_master_clean")
            kabupaten_clean = row.get("kabupaten_clean")
            kabupaten_master_clean = row.get("kabupaten_master_clean")
            kecamatan_clean = row.get("kecamatan_clean")
            kecamatan_master_clean = row.get("kecamatan_master_clean")
            kelurahan_clean = row.get("kelurahan_clean")
            kelurahan_master_clean = row.get("kelurahan_master_clean")

            score = self.scoring_service.compute_similarity_score(grade=grade,
                                b_nama=nama_clean, a_nama=nama_master_clean,
                                b_tempat_lahir=tempat_lahir_clean, a_tempat_lahir=tempat_lahir_master_clean,
                                b_tanggal_lahir=tanggal_lahir_clean, a_tanggal_lahir=tanggal_lahir_master_clean,
                                b_provinsi=provinsi_clean, a_provinsi=provinsi_master_clean,
                                b_kabupaten=kabupaten_clean, a_kabupaten=kabupaten_master_clean,
                                b_kecamatan=kecamatan_clean, a_kecamatan=kecamatan_master_clean,
                                b_kelurahan=kelurahan_clean, a_kelurahan=kelurahan_master_clean,
                                b_nama_ibu=nama_ibu_clean, a_nama_ibu=nama_ibu_master_clean)

            result = self.classify_result(grade, score, missing_count)
            existing = results_map.get(incoming_row_id)

            if (existing is None or score > existing["score"]):
                results_map[incoming_row_id] = {
                    "score": score,
                    "result": result,
                    "nik_master": row["nik_master"]
                }

        for incoming_id in all_incoming_ids:
            if incoming_id not in results_map:
                results_map[incoming_id] = {
                    "score": 0,
                    "result": 3,
                    "nik_master": None
                }

        results = []
        manual_review_rows = []
        for incoming_row_id, best_match in (results_map.items()):
            results.append({
                "id_incoming": incoming_row_id,
                "nik_master": best_match["nik_master"],
                "file_id": file_id,
                "match_score": round(best_match["score"], 2),
                "match_result": best_match["result"],
                "upload_date": uploaded_file["upload_timestamp"]
            })

            if best_match["result"] == 2:
                sync_status = 1
                incoming_row = (partition.filter(pl.col("id") == incoming_row_id).to_dicts()[0])

                manual_review_rows.append({
                    "file_id": file_id,
                    "id_incoming": incoming_row.get("id"),
                    "nik_incoming": None,
                    "nama_incoming": incoming_row.get("nama"),
                    "tempat_lahir_incoming": incoming_row.get("tempat_lahir"),
                    "area_incoming": None,
                    "tanggal_lahir_incoming": incoming_row.get("tanggal_lahir"),
                    "jenis_kelamin": incoming_row.get("jenis_kelamin"),
                    "nama_ibu_incoming": incoming_row.get("nama_ibu")
                })

        return results, manual_review_rows, sync_status

    def process_matching_job(self, file_id: str, grade: str, partition_size: int = 1_000_000):
        start_time = time.perf_counter()
        uploaded_file, incoming_df, master_df = (self.get_matching_data(file_id, grade))
        self.starrocks_service.set_sync_status_in_progress(file_id)

        start = time.perf_counter()
        all_results = []
        all_manual_review_rows = []
        final_sync_status = 3

        for idx, partition in enumerate(self.partition_dataframe(incoming_df, partition_size)):
            results, manual_review_rows, sync_status = self.process_partition(
                uploaded_file, partition, master_df, file_id, grade
            )

            all_results.extend(results)
            all_manual_review_rows.extend(manual_review_rows)

            if sync_status == 1:
                final_sync_status = 1

            partition_msg = (
                f"Partition {idx}: results={len(results):,}, "
                f"manual_reviews={len(manual_review_rows):,}"
            )
            self._log(partition_msg)
            print(partition_msg)

        insert_query = text("""
            INSERT INTO institution (
                id_incoming,
                nik_master,
                file_id,
                match_score,
                match_result,
                upload_date
            )
            VALUES (
                :id_incoming,
                :nik_master,
                :file_id,
                :match_score,
                :match_result,
                :upload_date
            )
        """)

        matched_time_query = text("""
            UPDATE uploaded_files
            SET matching_time_ms = :matching_time_ms
            WHERE file_id = :file_id
        """)

        matching_time_ms = round((time.perf_counter() - start) * 1000, 2)

        inst_msg = f"Institution rows: {len(all_results):,}"
        mr_msg   = f"Manual review rows: {len(all_manual_review_rows):,}"
        self._log(inst_msg)
        self._log(mr_msg)
        print(inst_msg)
        print(mr_msg)

        if all_manual_review_rows:
            self._log("First manual review row:")
            self._log(str(all_manual_review_rows[0]))
            print("First manual review row:")
            print(all_manual_review_rows[0])

        self.starrocks_service.insert_institution(
            insert_query, all_results, matched_time_query, matching_time_ms, file_id
        )

        if all_manual_review_rows:
            self.starrocks_service.insert_manual_review(all_manual_review_rows)

        self._log("Triggering AI...")
        print("Triggering AI...")
        self.trigger_ai_reasoning(file_id)
        self.starrocks_service.set_sync_complete(file_id, final_sync_status)

        self._log("Batch insert completed")
        print("Batch insert completed")

        if final_sync_status == 3:
            print(f"Auto-triggering export worker for file: {file_id}")
            generate_export_csv.apply_async(args=[file_id], queue="export_queue")

        response_data = {
            "message": f"Grade {grade} matching completed",
            "file_id": file_id,
            "processed_rows": len(all_results),
            "matched_rows": sum(
                1 for r in all_results if r["match_result"] == 1
            ),
            "manual_review_rows": sum(
                1 for r in all_results if r["match_result"] == 2
            ),
            "unmatched_rows": sum(
                1 for r in all_results if r["match_result"] == 3
            )
        }

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        self.audit_service.log_audit_event(
            actor_org_id="system_auto",
            action=f"MATCHING_GRADE_{grade}",
            resource_type="FILE",
            resource_id=file_id,
            result="SUCCESS",
            latency_ms=latency_ms,
            after_state=json.dumps(response_data)
        )

        return response_data