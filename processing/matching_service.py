import time
import json
import duckdb
import polars as pl
from sqlalchemy import text
from .string_similarity import ScoringService
from .minio_fetching_service import ObjectStorageService
from .repository import StarrocksService
from audit.audit_service import AuditService
from reasoning.tasks import trigger_rows_for_file

class MatchingService:
    def __init__(self, engine, minio_client, bucket_name, grade_rules):
        self.scoring_service = ScoringService()
        self.object_storage_service = ObjectStorageService(minio_client, bucket_name)
        self.starrocks_service = StarrocksService(engine)
        self.grade_rules = grade_rules
        self.audit_service = AuditService(engine)
        
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
        print(f"Incoming rows: {incoming_df.height}")

        master_df = self.starrocks_service.fetch_master_dataset()
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
            print(f"Enqueued reasoning orchestrator for file {file_id}")
        except Exception as e:
            print(f"Failed to enqueue reasoning orchestrator for {file_id}: {e}")

    def process_grade_a(self, file_id):
        start_time = time.perf_counter()
        uploaded_file, incoming_df, master_df = self.get_matching_data(file_id, 1)

        start = time.perf_counter()
        con = duckdb.connect()

        con.register(
            "incoming_df",
            incoming_df.to_arrow()
        )

        con.register(
            "master_df",
            master_df.to_arrow()
        )

        joined_df = con.execute("""
            SELECT
                i.id,
                i.nik,
                i.nama,
                i.nama_clean,
                m.nik AS nik_master,
                m.nama_lengkap,
                m.nama_master_clean
            FROM incoming_df i
            LEFT JOIN master_df m
                ON i.nik = m.nik
        """).pl()

        print(f"Joined rows: {joined_df.height}")

        results = []
        for row in joined_df.iter_rows(named=True):
            if row["nik_master"] is None:
                results.append({
                    "id_incoming": row["id"],
                    "nik_master": None,
                    "file_id": file_id,
                    "match_score": 0,
                    "match_result": 3,
                    "upload_date":
                        uploaded_file["upload_timestamp"]
                })

                continue

            score = self.scoring_service.safe_jaro(
                row["nama_clean"],
                row["nama_master_clean"]
            )

            score = round(score * 100, 2)

            result = (
                1
                if score > 80
                else 3
            )

            results.append({
                "id_incoming": row["id"],
                "nik_master": row["nik_master"],
                "file_id": file_id,
                "match_score": score,
                "match_result": result,
                "upload_date":
                    uploaded_file["upload_timestamp"]
            })
        matching_time_ms = round((time.perf_counter() - start) * 1000, 2)
        print(matching_time_ms)
        print(f"Results prepared: {len(results)}")

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
        
        self.starrocks_service.insert_institution(insert_query, results, matched_time_query, matching_time_ms, file_id, 3)
        print("Batch insert completed")

        response_data = {
            "message": "Grade A matching completed",
            "file_id": file_id,
            "processed_rows": len(results),
            "matched_rows": sum(
                1
                for r in results
                if r["match_result"] == 1
            ),
            "unmatched_rows": sum(
                1
                for r in results
                if r["match_result"] == 3
            )
        }

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        self.audit_service.log_audit_event(
            actor_org_id="system_auto", 
            action="MATCHING_GRADE_A",
            resource_type="FILE",
            resource_id=file_id,
            result="SUCCESS",
            latency_ms=latency_ms,
            after_state=json.dumps(response_data)
        )

        return response_data

    def count_missing_attributes(self, row):

        return sum([
            not row["nama_clean"],
            not row["tempat_lahir_clean"],
            not row["nama_ibu_clean"]
        ])

    def process_grade_b(self, file_id):
        start_time = time.perf_counter()
        uploaded_file, incoming_df, master_df = self.get_matching_data(file_id, 2)
        self.starrocks_service.set_sync_status_in_progress(file_id)
        start = time.perf_counter()
        con = duckdb.connect()
        con.register("incoming_df",incoming_df.to_arrow())

        con.register("master_df",master_df.to_arrow())

        joined_df = con.execute("""
            SELECT
                i.id,
                i.nik,
                i.nama,
                i.nama_clean,
                i.tempat_lahir,
                i.tempat_lahir_clean,
                i.nama_ibu,
                i.nama_ibu_clean,
                m.nik AS nik_master,
                m.nama_lengkap,
                m.nama_master_clean,
                m.tempat_lahir AS tempat_lahir_master,
                m.tempat_lahir_master_clean,
                m.nama_ibu AS nama_ibu_master,
                m.nama_ibu_master_clean
            FROM incoming_df i
            LEFT JOIN master_df m
                ON i.nik = m.nik
        """).pl()

        print(f"Joined rows: {joined_df.height}")

        results = []
        manual_review_rows = []
        sync_status = 3
        for row in joined_df.iter_rows(named=True):
            if row["nik_master"] is None:
                results.append({
                    "id_incoming": row["id"],
                    "nik_master": None,
                    "file_id": file_id,
                    "match_score": 0,
                    "match_result": 3,
                    "upload_date":
                        uploaded_file["upload_timestamp"]
                })
                continue

            missing_count = self.count_missing_attributes(row)

            score = round(
                self.scoring_service.compute_similarity_matched_grade_B(
                    row["nama_clean"],
                    row["nama_master_clean"],
                    row["tempat_lahir_clean"],
                    row["tempat_lahir_master_clean"],
                    row["nama_ibu_clean"],
                    row["nama_ibu_master_clean"]
                ),
                2
            )

            result = self.classify_result("B", score, missing_count)

            if result == 2:
                sync_status = 2

                manual_review_rows.append({
                    "file_id": file_id,
                    "id_incoming": row.get("id"),
                    "nik_incoming": row.get("nik"),
                    "nama_incoming": row.get("nama"),
                    "tempat_lahir_incoming": row.get("tempat_lahir"),
                    "area_incoming": None,
                    "tanggal_lahir_incoming": row.get("tanggal_lahir"),
                    "jenis_kelamin_incoming": row.get("jenis_kelamin"),
                    "nama_ibu_incoming": row.get("nama_ibu")
                })

            results.append({
                "id_incoming": row["id"],
                "nik_master": row["nik_master"],
                "file_id": file_id,
                "match_score": score,
                "match_result": result,
                "upload_date":
                    uploaded_file["upload_timestamp"]
            })

        matching_time_ms = round((time.perf_counter() - start) * 1000, 2)

        print(matching_time_ms)
        print(f"Results prepared: {len(results)}")

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

        self.starrocks_service.insert_institution(insert_query, results, matched_time_query, matching_time_ms, file_id)
        if manual_review_rows:
            self.starrocks_service.insert_manual_review(manual_review_rows)
        self.trigger_ai_reasoning(file_id)
        self.starrocks_service.set_sync_complete(file_id, sync_status)
        print("Batch insert completed")

        response_data = {
            "message": "Grade B matching completed",
            "file_id": file_id,
            "processed_rows": len(results),
            "matched_rows": sum(
                1
                for r in results
                if r["match_result"] == 1
            ),
            "manual_review_rows": sum(
                1
                for r in results
                if r["match_result"] == 2
            ),
            "unmatched_rows": sum(
                1
                for r in results
                if r["match_result"] == 3
            )
        }
        latency_ms = int((time.perf_counter() - start_time) * 1000) 
        self.audit_service.log_audit_event(
            actor_org_id="system_auto", 
            action="MATCHING_GRADE_B",
            resource_type="FILE",
            resource_id=file_id,
            result="SUCCESS",
            latency_ms=latency_ms,
            after_state=json.dumps(response_data)
        )

        return response_data

    
    def process_grade_c(self, file_id):
        start_time = time.perf_counter()
        uploaded_file, incoming_df, master_df = self.get_matching_data(file_id, 3)
        self.starrocks_service.set_sync_status_in_progress(file_id)
        start = time.perf_counter()
        con = duckdb.connect()

        con.register("incoming_df",incoming_df.to_arrow())
        con.register("master_df",master_df.to_arrow())

        candidate_query = """
            SELECT
                i.id,
                i.nama,
                i.nama_clean,
                i.tempat_lahir,
                i.tempat_lahir_clean,
                i.tanggal_lahir_clean,
                i.jenis_kelamin_clean,
                m.nik AS nik_master,
                m.nama_lengkap,
                m.nama_master_clean,
                m.tempat_lahir AS tempat_lahir_master,
                m.tempat_lahir_master_clean,
                m.tanggal_lahir_master_clean AS tanggal_lahir_master_clean,
                m.jenis_kelamin_master_clean AS jenis_kelamin_master_clean
            FROM incoming_df i
            LEFT JOIN master_df m
                ON i.jenis_kelamin_clean =
                m.jenis_kelamin_master_clean
                AND EXTRACT(
                    DAY FROM CAST(i.tanggal_lahir_clean AS DATE)
                ) = EXTRACT(
                    DAY FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                )
                AND EXTRACT(
                    MONTH FROM CAST(i.tanggal_lahir_clean AS DATE)
                ) = EXTRACT(
                    MONTH FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                )
                AND LEFT(i.nama_clean, 3) =
                    LEFT(m.nama_master_clean, 3)
        """

        candidate_df = con.execute(candidate_query).pl()
        print(f"Candidate rows: {candidate_df.height}")

        results_map = {}
        sync_status = 3
        for row in candidate_df.iter_rows(named=True):
            id_incoming = row["id"]
            if row["nik_master"] is None:
                if id_incoming not in results_map:
                    results_map[id_incoming] = {
                        "score": 0,
                        "result": 3,
                        "nik_master": None
                    }

                continue

            nama_score = self.scoring_service.safe_jaro(
                row["nama_clean"],
                row["nama_master_clean"]
            )
            tempat_lahir_score = self.scoring_service.safe_jaro(
                row["tempat_lahir_clean"],
                row["tempat_lahir_master_clean"]
            )
            tanggal_lahir_score = (
                1.0
                if row["tanggal_lahir_clean"] ==
                row["tanggal_lahir_master_clean"]
                else 0.0
            )
            final_score = (
                nama_score * 0.6 +
                tempat_lahir_score * 0.2 +
                tanggal_lahir_score * 0.2
            )

            existing = results_map.get(id_incoming)

            if (existing is None or final_score > existing["score"]):
                result = self.classify_result("C", final_score, 0)
                results_map[id_incoming] = {
                    "score": final_score,
                    "result": result,
                    "nik_master": row["nik_master"]
                }

        results = []
        manual_review_rows = []
        for id_incoming, best_match in results_map.items():
            results.append({
                "id_incoming": id_incoming,
                "nik_master": best_match["nik_master"],
                "file_id": file_id,
                "match_score": round(best_match["score"] * 100,2),
                "match_result": best_match["result"],
                "upload_date": uploaded_file["upload_timestamp"]
            })

            if best_match["result"] == 2:
                incoming_row = (
                    incoming_df
                    .filter(pl.col("id") == id_incoming)
                    .to_dicts()[0]
                )

                manual_review_rows.append({
                    "file_id": file_id,
                    "id_incoming": incoming_row.get("id"),
                    "nik_incoming": None,
                    "nama_incoming": incoming_row.get("nama"),
                    "tempat_lahir_incoming": incoming_row.get("tempat_lahir"),
                    "area_incoming": None,
                    "tanggal_lahir_incoming": incoming_row.get("tanggal_lahir"),
                    "jenis_kelamin_incoming": incoming_row.get("jenis_kelamin"),
                    "nama_ibu_incoming": incoming_row.get("nama_ibu")
                })

        matching_time_ms = round((time.perf_counter() - start) * 1000,2)
        print(f"Matching time: {matching_time_ms} ms")
        print(f"Results prepared: {len(results)}")
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

        self.starrocks_service.insert_institution(insert_query, results, matched_time_query, matching_time_ms, file_id)
        if manual_review_rows:
            self.starrocks_service.insert_manual_review(manual_review_rows)
        self.trigger_ai_reasoning(file_id)
        self.starrocks_service.set_sync_complete(file_id, sync_status)
        print("Batch insert completed")
        
        response_data = {
            "message": "Grade C matching completed",
            "file_id": file_id,
            "processed_rows": len(results),
            "matched_rows": sum(
                1
                for r in results
                if r["match_result"] == 1
            ),
            "manual_review_rows": sum(
                1
                for r in results
                if r["match_result"] == 2
            ),
            "unmatched_rows": sum(
                1
                for r in results
                if r["match_result"] == 3
            )
        }

        latency_ms = int((time.perf_counter() - start_time) * 1000) 
        self.audit_service.log_audit_event(
            actor_org_id="system_auto", 
            action="MATCHING_GRADE_C",
            resource_type="FILE",
            resource_id=file_id,
            result="SUCCESS",
            latency_ms=latency_ms,
            after_state=json.dumps(response_data)
        )

        return response_data
    
    def process_grade_d(self, file_id):
        start_time = time.perf_counter()
        uploaded_file, incoming_df, master_df = self.get_matching_data(file_id, 4)
        self.starrocks_service.set_sync_status_in_progress(file_id)
        start = time.perf_counter()
        con = duckdb.connect()
        con.register("incoming_df",incoming_df.to_arrow())
        con.register("master_df",master_df.to_arrow())

        candidate_query = """
            WITH missing_gender AS (
                SELECT
                    i.id AS incoming_row_id,
                    i.nama_clean,
                    i.tempat_lahir_clean,
                    i.tanggal_lahir_clean,
                    i.nama_ibu_clean,
                    i.jenis_kelamin_clean,
                    m.nik AS nik_master,
                    m.nama_master_clean,
                    m.tempat_lahir_master_clean,
                    m.tanggal_lahir_master_clean,
                    m.nama_ibu_master_clean,
                    m.jenis_kelamin_master_clean
                FROM incoming_df i
                INNER JOIN master_df m
                    ON i.jenis_kelamin_clean IS NULL
                    AND i.tempat_lahir_clean IS NOT NULL
                    AND i.tempat_lahir_clean != ''
                    AND m.tempat_lahir_master_clean IS NOT NULL
                    AND m.tempat_lahir_master_clean != ''
                    AND LEFT(i.tempat_lahir_clean, 3)
                        =
                        LEFT(m.tempat_lahir_master_clean, 3)
                    AND EXTRACT(
                        DAY FROM CAST(i.tanggal_lahir_clean AS DATE)
                    )
                    =
                    EXTRACT(
                        DAY FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                    )
                    AND EXTRACT(
                        MONTH FROM CAST(i.tanggal_lahir_clean AS DATE)
                    )
                    =
                    EXTRACT(
                        MONTH FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                    )
            ),
            missing_tempat AS (
                SELECT
                    i.id AS incoming_row_id,
                    i.nama_clean,
                    i.tempat_lahir_clean,
                    i.tanggal_lahir_clean,
                    i.nama_ibu_clean,
                    i.jenis_kelamin_clean,
                    m.nik AS nik_master,
                    m.nama_master_clean,
                    m.tempat_lahir_master_clean,
                    m.tanggal_lahir_master_clean,
                    m.nama_ibu_master_clean,
                    m.jenis_kelamin_master_clean
                FROM incoming_df i
                INNER JOIN master_df m
                    ON i.tempat_lahir_clean IS NULL
                    AND i.jenis_kelamin_clean =
                        m.jenis_kelamin_master_clean
                    AND i.nama_clean IS NOT NULL
                    AND i.nama_clean != ''
                    AND m.nama_master_clean IS NOT NULL
                    AND m.nama_master_clean != ''
                    AND LEFT(i.nama_clean, 3)
                        =
                        LEFT(m.nama_master_clean, 3)
                    AND EXTRACT(
                        DAY FROM CAST(i.tanggal_lahir_clean AS DATE)
                    )
                    =
                    EXTRACT(
                        DAY FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                    )
                    AND EXTRACT(
                        MONTH FROM CAST(i.tanggal_lahir_clean AS DATE)
                    )
                    =
                    EXTRACT(
                        MONTH FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                    )
            ),
            missing_tanggal AS (
                SELECT
                    i.id AS incoming_row_id,
                    i.nama_clean,
                    i.tempat_lahir_clean,
                    i.tanggal_lahir_clean,
                    i.nama_ibu_clean,
                    i.jenis_kelamin_clean,
                    m.nik AS nik_master,
                    m.nama_master_clean,
                    m.tempat_lahir_master_clean,
                    m.tanggal_lahir_master_clean,
                    m.nama_ibu_master_clean,
                    m.jenis_kelamin_master_clean
                FROM incoming_df i
                INNER JOIN master_df m
                    ON i.tanggal_lahir_clean IS NULL
                    AND i.jenis_kelamin_clean =
                        m.jenis_kelamin_master_clean
                    AND i.tempat_lahir_clean IS NOT NULL
                    AND i.tempat_lahir_clean != ''
                    AND m.tempat_lahir_master_clean IS NOT NULL
                    AND m.tempat_lahir_master_clean != ''
                    AND LEFT(i.tempat_lahir_clean, 3)
                        =
                        LEFT(m.tempat_lahir_master_clean, 3)
                    AND i.nama_clean IS NOT NULL
                    AND i.nama_clean != ''
                    AND m.nama_master_clean IS NOT NULL
                    AND m.nama_master_clean != ''
                    AND LEFT(i.nama_clean, 3)
                        =
                        LEFT(m.nama_master_clean, 3)
            ),
            complete_data AS (
                SELECT
                    i.id AS incoming_row_id,
                    i.nama_clean,
                    i.tempat_lahir_clean,
                    i.tanggal_lahir_clean,
                    i.nama_ibu_clean,
                    i.jenis_kelamin_clean,
                    m.nik AS nik_master,
                    m.nama_master_clean,
                    m.tempat_lahir_master_clean,
                    m.tanggal_lahir_master_clean,
                    m.nama_ibu_master_clean,
                    m.jenis_kelamin_master_clean
                FROM incoming_df i
                INNER JOIN master_df m
                    ON i.jenis_kelamin_clean =
                        m.jenis_kelamin_master_clean
                    AND LEFT(i.nama_clean, 3)
                        =
                        LEFT(m.nama_master_clean, 3)
                    AND EXTRACT(
                        DAY FROM CAST(i.tanggal_lahir_clean AS DATE)
                    )
                    =
                    EXTRACT(
                        DAY FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                    )
                    AND EXTRACT(
                        MONTH FROM CAST(i.tanggal_lahir_clean AS DATE)
                    )
                    =
                    EXTRACT(
                        MONTH FROM CAST(m.tanggal_lahir_master_clean AS DATE)
                    )
            )
            SELECT DISTINCT *
            FROM (
                SELECT * FROM missing_gender
                UNION ALL
                SELECT * FROM missing_tempat
                UNION ALL
                SELECT * FROM missing_tanggal
                UNION ALL
                SELECT * FROM complete_data
            )
        """

        candidate_df = con.execute(candidate_query).pl()
        con.close()

        print(f"Candidate rows: {candidate_df.height}")
        results_map = {}
        sync_status = 3

        all_incoming_ids = (
            incoming_df
            .select("id")
            .to_series()
            .to_list()
        )

        for incoming_id in all_incoming_ids:
            if incoming_id not in results_map:
                results_map[incoming_id] = {
                    "score": 0,
                    "result": 3,
                    "nik_master": None
                }

        for row in candidate_df.iter_rows(named=True):
            incoming_row_id = row["incoming_row_id"]
            if row["nik_master"] is None:
                if incoming_row_id not in results_map:
                    results_map[incoming_row_id] = {
                        "score": 0,
                        "result": 3,
                        "nik_master": None
                    }

                continue

            missing_count = 0

            if not row["tempat_lahir_clean"]:
                missing_count += 1
            if not row["tanggal_lahir_clean"]:
                missing_count += 1
            if not row["nama_ibu_clean"]:
                missing_count += 1

            weighted_score = 0
            active_weight = 0

            nama_score = self.scoring_service.safe_jaro(row["nama_clean"],row["nama_master_clean"])

            weighted_score += nama_score * 0.6
            active_weight += 0.6

            if row["tempat_lahir_clean"]:
                tempat_score = (
                    self.scoring_service.safe_jaro(
                        row["tempat_lahir_clean"],
                        row["tempat_lahir_master_clean"]
                    )
                )

                weighted_score += tempat_score * 0.05
                active_weight += 0.05

            if row["tanggal_lahir_clean"]:
                tanggal_score = (
                    1.0
                    if row["tanggal_lahir_clean"]
                    ==
                    row["tanggal_lahir_master_clean"]
                    else 0.0
                )

                weighted_score += tanggal_score * 0.3
                active_weight += 0.3

            if row["nama_ibu_clean"]:
                ibu_score = (
                    self.scoring_service.safe_jaro(
                        row["nama_ibu_clean"],
                        row["nama_ibu_master_clean"]
                    )
                )

                weighted_score += ibu_score * 0.05
                active_weight += 0.05

            final_score = (weighted_score / active_weight)

            result = self.classify_result("D", final_score, missing_count)
            existing = results_map.get(incoming_row_id)

            if (existing is None or final_score > existing["score"]):
                results_map[incoming_row_id] = {
                    "score": final_score,
                    "result": result,
                    "nik_master": row["nik_master"]
                }

        results = []
        manual_review_rows = []
        for incoming_row_id, best_match in (results_map.items()):
            results.append({
                "id_incoming": incoming_row_id,
                "nik_master": best_match["nik_master"],
                "file_id": file_id,
                "match_score": round(best_match["score"] * 100, 2),
                "match_result": best_match["result"],
                "upload_date": uploaded_file["upload_timestamp"]
            })

            if best_match["result"] == 2:
                incoming_row = (
                    incoming_df
                    .filter(pl.col("id") == incoming_row_id)
                    .to_dicts()[0]
                )

                manual_review_rows.append({
                    "file_id": file_id,
                    "id_incoming": incoming_row.get("id"),
                    "nik_incoming": None,
                    "nama_incoming": incoming_row.get("nama"),
                    "tempat_lahir_incoming": incoming_row.get("tempat_lahir"),
                    "area_incoming": None,
                    "tanggal_lahir_incoming": incoming_row.get("tanggal_lahir"),
                    "jenis_kelamin_incoming": incoming_row.get("jenis_kelamin"),
                    "nama_ibu_incoming": incoming_row.get("nama_ibu")
                })

        matching_time_ms = round(
            (
                time.perf_counter() - start
            ) * 1000,
            2
        )

        print(f"Matching time: "f"{matching_time_ms} ms")
        print(f"Results prepared: "f"{len(results)}")

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

            SET matching_time_ms =
                :matching_time_ms

            WHERE file_id = :file_id
        """)

        self.starrocks_service.insert_institution(insert_query, results, matched_time_query, matching_time_ms, file_id)
        if manual_review_rows:
            self.starrocks_service.insert_manual_review(manual_review_rows)
        print('Triggering AI...')
        self.trigger_ai_reasoning(file_id)
        self.starrocks_service.set_sync_complete(file_id, sync_status)
        print("Batch insert completed")

        response_data = {
            "message": "Grade D matching completed",
            "file_id": file_id,
            "processed_rows": len(results),
            "matched_rows":
                sum(
                    1
                    for r in results
                    if r["match_result"]
                    == 1
                ),
            "manual_review_rows":
                sum(
                    1
                    for r in results
                    if r["match_result"]
                    == 2
                ),
            "unmatched_rows":
                sum(
                    1
                    for r in results
                    if r["match_result"]
                    == 3
                )
        }

        latency_ms = int((time.perf_counter() - start_time) * 1000) 
        self.audit_service.log_audit_event(
            actor_org_id="system_auto", 
            action="MATCHING_GRADE_D",
            resource_type="FILE",
            resource_id=file_id,
            result="SUCCESS",
            latency_ms=latency_ms,
            after_state=json.dumps(response_data)
        )

        return response_data

    def process_grade_e(self, file_id):
        start_time = time.perf_counter()
        uploaded_file, incoming_df, master_df = self.get_matching_data(file_id, 5)
        self.starrocks_service.set_sync_status_in_progress(file_id)
        start = time.perf_counter()
        con = duckdb.connect()
        con.register("incoming_df",incoming_df.to_arrow())
        con.register("master_df",master_df.to_arrow())

        candidate_query = """
            WITH candidates AS (
                SELECT
                    i.id AS incoming_row_id,
                    i.nama_clean,
                    i.tanggal_lahir_clean,
                    i.provinsi_clean,
                    i.kabupaten_clean,
                    i.kecamatan_clean,
                    i.kelurahan_clean,
                    i.nama_ibu_clean,
                    i.status_hidup_clean,
                    m.nik AS nik_master,
                    m.nama_master_clean,
                    m.tanggal_lahir_master_clean,
                    m.provinsi_master_clean,
                    m.kabupaten_master_clean,
                    m.kecamatan_master_clean,
                    m.kelurahan_master_clean,
                    m.nama_ibu_master_clean,
                    m.status_hidup_master_clean
                FROM incoming_df i
                INNER JOIN master_df m
                    ON i.status_hidup_clean =
                        m.status_hidup_master_clean
                    AND i.nama_clean IS NOT NULL
                    AND i.nama_clean != ''
                    AND m.nama_master_clean IS NOT NULL
                    AND m.nama_master_clean != ''
                    AND LEFT(i.nama_clean, 3)
                        =
                        LEFT(m.nama_master_clean, 3)
                    AND i.tanggal_lahir_clean IS NOT NULL
                    AND m.tanggal_lahir_master_clean
                        IS NOT NULL
                    AND EXTRACT(
                        DAY FROM CAST(
                            i.tanggal_lahir_clean AS DATE
                        )
                    )
                    =
                    EXTRACT(
                        DAY FROM CAST(
                            m.tanggal_lahir_master_clean
                            AS DATE
                        )
                    )
                    AND EXTRACT(
                        MONTH FROM CAST(
                            i.tanggal_lahir_clean AS DATE
                        )
                    )
                    =
                    EXTRACT(
                        MONTH FROM CAST(
                            m.tanggal_lahir_master_clean
                            AS DATE
                        )
                    )
            )
            SELECT DISTINCT *
            FROM candidates
        """

        candidate_df = con.execute(
            candidate_query
        ).pl()
        con.close()
        print(f"Candidate rows: {candidate_df.height}")

        results_map = {}
        sync_status = 3
        for row in candidate_df.iter_rows(named=True):
            incoming_row_id = row["incoming_row_id"]
            if row["nik_master"] is None:
                if incoming_row_id not in results_map:
                    results_map[incoming_row_id] = {
                        "score": 0,
                        "result": 3,
                        "nik_master": None
                    }

                continue

            missing_count = 0
            if (not row["nama_clean"]):
                missing_count += 1
            if (not row["tanggal_lahir_clean"]):
                missing_count += 1
            area_exists = any([
                row["provinsi_clean"],
                row["kabupaten_clean"],
                row["kecamatan_clean"],
                row["kelurahan_clean"]
            ])
            if not area_exists:
                missing_count += 1
            if (not row["nama_ibu_clean"]):
                missing_count += 1

            weighted_score = 0
            active_weight = 0

            if row["nama_clean"]:
                nama_score = (
                    self.scoring_service.safe_jaro(
                        row["nama_clean"],
                        row["nama_master_clean"]
                    )
                )
                weighted_score += nama_score * 0.5
                active_weight += 0.5

            if row["tanggal_lahir_clean"]:
                tanggal_score = (
                    1.0
                    if row["tanggal_lahir_clean"]
                    ==
                    row["tanggal_lahir_master_clean"]
                    else 0.0
                )
                weighted_score += tanggal_score * 0.1
                active_weight += 0.1

            area_scores = []

            if (row["provinsi_clean"] and row["provinsi_master_clean"]):
                area_scores.append(
                    self.scoring_service.safe_jaro(
                        row["provinsi_clean"],
                        row["provinsi_master_clean"]
                    )
                )
            if (row["kabupaten_clean"] and row["kabupaten_master_clean"]):
                area_scores.append(
                    self.scoring_service.safe_jaro(
                        row["kabupaten_clean"],
                        row["kabupaten_master_clean"]
                    )
                )

            if (row["kecamatan_clean"] and row["kecamatan_master_clean"]):
                area_scores.append(
                    self.scoring_service.safe_jaro(
                        row["kecamatan_clean"],
                        row["kecamatan_master_clean"]
                    )
                )

            if (row["kelurahan_clean"] and row["kelurahan_master_clean"]):
                area_scores.append(
                    self.scoring_service.safe_jaro(
                        row["kelurahan_clean"],
                        row["kelurahan_master_clean"]
                    )
                )

            if len(area_scores) > 0:
                area_score = (sum(area_scores) / len(area_scores))
                weighted_score += area_score * 0.3
                active_weight += 0.3

            if row["nama_ibu_clean"]:
                ibu_score = (
                    self.scoring_service.safe_jaro(
                        row["nama_ibu_clean"],
                        row["nama_ibu_master_clean"]
                    )
                )
                weighted_score += ibu_score * 0.1
                active_weight += 0.1

            final_score = (weighted_score / active_weight if active_weight > 0 else 0)

            result = self.classify_result("E", final_score, missing_count)

            existing = results_map.get(incoming_row_id)

            if (existing is None or final_score > existing["score"]):
                results_map[incoming_row_id] = {
                    "score": final_score,
                    "result": result,
                    "nik_master": row["nik_master"]
                }

        all_incoming_ids = set(incoming_df["id"].to_list())
        matched_incoming_ids = set(results_map.keys())
        missing_incoming_ids = (all_incoming_ids - matched_incoming_ids)
        print(f"Rows without candidates: "f"{len(missing_incoming_ids)}")

        for incoming_row_id in missing_incoming_ids:
            results_map[incoming_row_id] = {
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
                "match_score":
                    round(
                        best_match["score"] * 100,
                        2
                    ),
                "match_result":
                    best_match["result"],
                "upload_date":
                    uploaded_file[
                        "upload_timestamp"
                    ]
            })

            if best_match["result"] == 2:
                incoming_row = (
                    incoming_df
                    .filter(pl.col("id") == incoming_row_id)
                    .to_dicts()[0]
                )

                area_parts = [
                    incoming_row.get("provinsi"),
                    incoming_row.get("kabupaten"),
                    incoming_row.get("kecamatan"),
                    incoming_row.get("kelurahan")
                ]

                area_incoming = ", ".join(
                    str(x).strip()
                    for x in area_parts
                    if x is not None and str(x).strip()
                )

                manual_review_rows.append({
                    "file_id": file_id,
                    "id_incoming": incoming_row.get("id"),
                    "nik_incoming": incoming_row.get("nik"),
                    "nama_incoming": incoming_row.get("nama"),
                    "tempat_lahir_incoming": incoming_row.get("tempat_lahir"),
                    "area_incoming": area_incoming,
                    "tanggal_lahir_incoming": incoming_row.get("tanggal_lahir"),
                    "nama_ibu_incoming": incoming_row.get("nama_ibu")
                })

        matching_time_ms = round(
            (
                time.perf_counter() - start
            ) * 1000,
            2
        )

        print(f"Matching time: "f"{matching_time_ms} ms")
        print(f"Results prepared: "f"{len(results)}")

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
            SET matching_time_ms =
                :matching_time_ms
            WHERE file_id = :file_id
        """)

        self.starrocks_service.insert_institution(insert_query, results, matched_time_query, matching_time_ms, file_id)
        if manual_review_rows:
            self.starrocks_service.insert_manual_review(manual_review_rows)
        self.trigger_ai_reasoning(file_id)
        self.starrocks_service.set_sync_complete(file_id, sync_status)
        print("Batch insert completed")

        response_data = {
            "message": "Grade E matching completed",
            "file_id": file_id,
            "processed_rows": len(results),
            "matched_rows":
                sum(
                    1
                    for r in results
                    if r["match_result"]
                    == 1
                ),
            "manual_review_rows":
                sum(
                    1
                    for r in results
                    if r["match_result"]
                    == 2
                ),
            "unmatched_rows":
                sum(
                    1
                    for r in results
                    if r["match_result"]
                    == 3
                )
        }

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        self.audit_service.log_audit_event(
            actor_org_id="system_auto", 
            action="MATCHING_GRADE_E",
            resource_type="FILE",
            resource_id=file_id,
            result="SUCCESS",
            latency_ms=latency_ms,
            after_state=json.dumps(response_data)
        )

        return response_data