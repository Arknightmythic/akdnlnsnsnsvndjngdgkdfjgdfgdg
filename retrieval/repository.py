from sqlalchemy import text

class RetrieveRepository:
    def __init__(self, engine):
        self.engine = engine

    def get_graded_files(self, page, page_size):
        offset = (page - 1) * page_size

        count_query = text("SELECT COUNT(*) AS total FROM uploaded_files")

        data_query = text("""
            SELECT
                uf.file_id,
                uf.original_filename,
                uf.institution_name,
                uf.upload_timestamp,
                rg.grade_code as grade,
                uf.row_count,
                rp.process_name as processing_status,
                uf.is_sync,
                uf.matching_task_status
            FROM uploaded_files uf
            INNER JOIN ref_grades rg ON uf.grade = rg.grade_id
            INNER JOIN ref_process rp ON uf.processing_status = rp.process_id
            ORDER BY uf.upload_timestamp DESC
            LIMIT :limit OFFSET :offset
        """)

        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query).scalar()
            rows = conn.execute(data_query, {"limit": page_size, "offset": offset}).mappings().all()

        return [dict(row) for row in rows], total_rows

    def get_synchronized_files(self, page, page_size, institution_name, grade, sync_status):
        offset = (page - 1) * page_size
        where_conditions = []
        params = {"limit": page_size, "offset": offset}

        if institution_name and institution_name.strip("'").strip():
            where_conditions.append("LOWER(uf.institution_name) LIKE LOWER(:institution_name)")
            params["institution_name"] = f"%{institution_name.strip(chr(39)).strip()}%"

        if grade:
            grade_list = [g.strip() for g in str(grade).split(",") if g.strip()]
            if grade_list:
                placeholders = ", ".join([f":grade_{i}" for i in range(len(grade_list))])
                where_conditions.append(f"rg.grade_id IN ({placeholders})")
                for i, g in enumerate(grade_list):
                    params[f"grade_{i}"] = int(g)

        if sync_status:
            status_list = [s.strip() for s in str(sync_status).split(",") if s.strip()]
            if status_list:
                placeholders = ", ".join([f":sync_status_{i}" for i in range(len(status_list))])
                where_conditions.append(f"rs.sync_status_id IN ({placeholders})")
                for i, s in enumerate(status_list):
                    params[f"sync_status_{i}"] = int(s)

        where_clause = f"WHERE {' AND '.join(where_conditions)}" if where_conditions else ""

        count_query = text(f"""
            SELECT COUNT(*)
            FROM uploaded_files uf
            JOIN ref_grades rg ON uf.grade = rg.grade_id
            JOIN ref_sync_statuses rs ON uf.sync_status = rs.sync_status_id
            {where_clause}
        """)

        data_query = text(f"""
            SELECT
                uf.file_id, uf.original_filename, uf.institution_name,
                uf.upload_timestamp, rg.grade_code AS grade,
                uf.row_count, uf.is_sync, rs.status_code AS sync_status
            FROM uploaded_files uf
            JOIN ref_grades rg ON uf.grade = rg.grade_id
            JOIN ref_sync_statuses rs ON uf.sync_status = rs.sync_status_id
            {where_clause}
            ORDER BY uf.upload_timestamp DESC
            LIMIT :limit OFFSET :offset
        """)

        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query, params).scalar()
            rows = conn.execute(data_query, params).mappings().all()

        return [dict(row) for row in rows], total_rows

    def get_history_data(self, page, page_size, institution_name, start_date, end_date):
        offset = (page - 1) * page_size
        where_conditions = []
        params = {"limit": page_size, "offset": offset}

        if institution_name and institution_name.strip("'").strip():
            where_conditions.append("LOWER(uf.institution_name) LIKE LOWER(:institution_name)")
            params["institution_name"] = f"%{institution_name.strip(chr(39)).strip()}%"

        if start_date:
            where_conditions.append("DATE(uf.upload_timestamp) >= :start_date")
            params["start_date"] = start_date

        if end_date:
            where_conditions.append("DATE(uf.upload_timestamp) <= :end_date")
            params["end_date"] = end_date

        where_clause = f"WHERE {' AND '.join(where_conditions)}" if where_conditions else ""

        count_query = text(f"""
            SELECT COUNT(*)
            FROM uploaded_files uf
            JOIN ref_grades rg ON uf.grade = rg.grade_id
            JOIN ref_sync_statuses rs ON uf.sync_status = rs.sync_status_id
            {where_clause}
            AND uf.sync_status = 3
        """)

        data_query = text(f"""
            SELECT
                uf.file_id,
                uf.institution_name,
                uf.original_filename,
                uf.upload_timestamp,
                uf.export_status, -- TAMBAHKAN KOLOM INI

                SUM(CASE WHEN i.match_result = 1 THEN 1 ELSE 0 END) AS total_auto_match,
                SUM(CASE WHEN i.match_result = 4 THEN 1 ELSE 0 END) AS total_manual_match,
                SUM(CASE WHEN i.match_result IN (3, 5) THEN 1 ELSE 0 END) AS total_unmatch

            FROM uploaded_files uf
            INNER JOIN institution i
                ON i.file_id = uf.file_id

            {where_clause}
            AND uf.sync_status = 3

            GROUP BY
                uf.file_id,
                uf.institution_name,
                uf.original_filename,
                uf.upload_timestamp,
                uf.export_status -- TAMBAHKAN INI JUGA

            ORDER BY uf.upload_timestamp DESC
            LIMIT :limit
            OFFSET :offset
        """)

        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query, params).scalar()
            rows = conn.execute(data_query, params).mappings().all()

        return [dict(row) for row in rows], total_rows

    def get_minio_path(self, file_id: str):
        q = text("""
            SELECT minio_path, is_sync, sync_status
            FROM uploaded_files WHERE file_id = :file_id
        """)
        with self.engine.connect() as conn:
            return conn.execute(q, {"file_id": file_id}).mappings().first()

    def get_completed_data(self, file_id: str):
        match_query = text("""
            SELECT
                i.id_incoming,
                i.nik_master,
                i.match_score,
                mr.match_result_name,
                i.file_id
            FROM institution i
            JOIN ref_match_results mr
            WHERE i.file_id = :file_id 
            AND i.match_result = mr.match_result_id
            AND i.match_result IN (1,4)
            ORDER BY i.match_score DESC
            LIMIT 10
        """)

        unmatch_query = text("""
            SELECT
                i.id_incoming,
                i.match_score,
                mr.match_result_name,
                i.file_id
            FROM institution i
            JOIN ref_match_results mr
            WHERE i.file_id = :file_id
            AND i.match_result = mr.match_result_id
            AND i.match_result IN (3,5)
            ORDER BY i.match_score ASC
            LIMIT 10
        """)
        with self.engine.connect() as conn:
            matches   = conn.execute(match_query,   {"file_id": file_id}).mappings().all()
            unmatches = conn.execute(unmatch_query, {"file_id": file_id}).mappings().all()

        return {
            "match":   [dict(row) for row in matches],
            "unmatch": [dict(row) for row in unmatches],
        }

    def get_manual_review_data(self, file_id: str, page, page_size):
        offset = (page - 1) * page_size

        count_query = text("""
            SELECT COUNT(*) AS total
            FROM (
                SELECT
                    i.id_incoming,
                    i.nik_master,
                    i.match_score,
                    mr.match_result_name,
                    i.file_id,
                    mm.reason
                FROM institution i
                JOIN ref_match_results mr ON i.match_result = mr.match_result_id
                JOIN manual_matches mm ON i.id_incoming = mm.id_incoming
                WHERE i.file_id = :file_id 
                AND i.match_result = 2
                AND i.match_result = mr.match_result_id
                AND i.id_incoming = mm.id_incoming
            ) s
        """)

        manual_review_query = text("""
            SELECT
                i.id_incoming,
                i.nik_master,
                i.match_score,
                mr.match_result_name,
                i.file_id,
                mm.reason
            FROM institution i
            JOIN ref_match_results mr ON i.match_result = mr.match_result_id
            JOIN manual_matches mm ON i.id_incoming = mm.id_incoming AND i.file_id = mm.file_id
            WHERE i.file_id = :file_id 
            AND i.match_result = 2
            AND i.match_result = mr.match_result_id
            AND i.id_incoming = mm.id_incoming
            ORDER BY i.match_score ASC, i.id_incoming ASC
            LIMIT :limit
            OFFSET :offset
        """)

        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query, {"file_id": file_id}).scalar()
            rows = conn.execute(
                manual_review_query,
                {"file_id": file_id, "limit": page_size, "offset": offset}
            ).mappings().all()

        return [dict(row) for row in rows], total_rows

    def get_master_by_niks(self, niks):
        if not niks:
            return {}

        unique_niks  = list(set(niks))
        CHUNK_SIZE   = 5000
        result_map   = {}

        q = text("""
            SELECT nik, nama_lengkap, tempat_lahir, tanggal_lahir, jenis_kelamin,
                   nama_ibu, provinsi, kabupaten, kecamatan, kelurahan, status_kematian
            FROM master WHERE nik IN :niks
        """)

        with self.engine.connect() as conn:
            for i in range(0, len(unique_niks), CHUNK_SIZE):
                chunk = unique_niks[i:i + CHUNK_SIZE]
                rows  = conn.execute(q, {"niks": tuple(chunk)}).mappings().all()
                for r in rows:
                    result_map[r["nik"]] = dict(r)

        return result_map

    # -----------------------------------------------------------------------
    # BEFORE_STATE helpers
    # -----------------------------------------------------------------------

    def get_match_result_before(self, id_incoming: str, file_id: str) -> dict:
        """
        Fetch match_result saat ini dari institution SEBELUM di-update.
        Dipakai sebagai before_state untuk audit MARK_MATCH_STATUS.
        Hanya ambil match_result — tidak perlu seluruh row.
        """
        q = text("""
            SELECT match_result
            FROM institution
            WHERE id_incoming = :id_incoming AND file_id = :file_id
            LIMIT 1
        """)
        with self.engine.connect() as conn:
            row = conn.execute(q, {"id_incoming": id_incoming, "file_id": file_id}).mappings().first()
        return dict(row) if row else {}

    def get_file_status_before(self, file_id: str) -> dict:
        """
        Fetch sync_status dan is_sync dari uploaded_files SEBELUM di-update.
        Dipakai sebagai before_state untuk audit MARK_FILE_COMPLETED.
        """
        q = text("""
            SELECT sync_status, is_sync
            FROM uploaded_files
            WHERE file_id = :file_id
            LIMIT 1
        """)
        with self.engine.connect() as conn:
            row = conn.execute(q, {"file_id": file_id}).mappings().first()
        return dict(row) if row else {}

    def get_matching_status_before(self, file_id: str) -> dict:
        """
        Fetch matching_task_status dan sync_status SEBELUM proses matching dimulai.
        Dipakai sebagai before_state untuk audit MATCHING_GRADE_X.
        """
        q = text("""
            SELECT matching_task_status, sync_status, is_sync
            FROM uploaded_files
            WHERE file_id = :file_id
            LIMIT 1
        """)
        with self.engine.connect() as conn:
            row = conn.execute(q, {"file_id": file_id}).mappings().first()
        return dict(row) if row else {}

    def count_events_before_retention(self) -> dict:
        """
        Hitung jumlah baris audit_event dan access_event SEBELUM dihapus oleh retention.
        Dipakai sebagai before_state untuk audit execute_audit_retention.
        """
        q = text("""
            SELECT
                (SELECT COUNT(*) FROM audit_event)  AS audit_event_count,
                (SELECT COUNT(*) FROM access_event) AS access_event_count
        """)
        with self.engine.connect() as conn:
            row = conn.execute(q).mappings().first()
        return dict(row) if row else {"audit_event_count": 0, "access_event_count": 0}

    # -----------------------------------------------------------------------
    # Write operations
    # -----------------------------------------------------------------------

    def mark_manual_match(self, id_incoming, file_id):
        query = text("""
            UPDATE institution
            SET match_result = 4
            WHERE id_incoming = :id_incoming AND file_id = :file_id AND match_result = 2
        """)
        with self.engine.begin() as conn:
            result = conn.execute(query, {"id_incoming": id_incoming, "file_id": file_id})
        return result.rowcount

    def mark_manual_unmatch(self, id_incoming, file_id):
        query = text("""
            UPDATE institution
            SET match_result = 5
            WHERE id_incoming = :id_incoming AND file_id = :file_id AND match_result = 2
        """)
        with self.engine.begin() as conn:
            result = conn.execute(query, {"id_incoming": id_incoming, "file_id": file_id})
        return result.rowcount

    def mark_as_completed(self, file_id):
        query1 = text("""
            UPDATE institution
            SET match_result = 5
            WHERE match_result = 2 AND file_id = :file_id
        """)
        query2 = text("""
            UPDATE uploaded_files
            SET sync_status = 3
            WHERE file_id = :file_id AND sync_status = 2
        """)
        with self.engine.begin() as conn:
            r1 = conn.execute(query1, {"file_id": file_id})
            r2 = conn.execute(query2, {"file_id": file_id})
        return {"institution_updated": r1.rowcount, "file_updated": r2.rowcount}

    def get_all_export_data(self, file_id: str):
        match_query = text("""
            SELECT i.id_incoming, i.nik_master, i.match_score, mr.match_result_name
            FROM institution i JOIN ref_match_results mr ON i.match_result = mr.match_result_id
            WHERE i.file_id = :file_id AND i.match_result IN (1,4)
        """)
        unmatch_query = text("""
            SELECT i.id_incoming, i.match_score, mr.match_result_name
            FROM institution i JOIN ref_match_results mr ON i.match_result = mr.match_result_id
            WHERE i.file_id = :file_id AND i.match_result IN (3,5)
        """)
        with self.engine.connect() as conn:
            matches   = conn.execute(match_query,   {"file_id": file_id}).mappings().all()
            unmatches = conn.execute(unmatch_query, {"file_id": file_id}).mappings().all()

        return {
            "match":   [dict(row) for row in matches],
            "unmatch": [dict(row) for row in unmatches],
        }

    def update_export_status(self, file_id: str, status: str, match_path: str = None, unmatch_path: str = None):
        query = text("""
            UPDATE uploaded_files
            SET export_status = :status,
                export_match_path   = COALESCE(:match_path,   export_match_path),
                export_unmatch_path = COALESCE(:unmatch_path, export_unmatch_path)
            WHERE file_id = :file_id
        """)
        with self.engine.begin() as conn:
            conn.execute(query, {
                "file_id": file_id, "status": status,
                "match_path": match_path, "unmatch_path": unmatch_path,
            })

    def get_summary_dashboard(self):
        query1 = text("""
            SELECT
                COUNT(*) AS total_files,
                SUM(CASE WHEN is_sync = 0 THEN 1 ELSE 0 END) AS total_pending,
                SUM(CASE WHEN is_sync = 1 AND sync_status = 3 THEN 1 ELSE 0 END) AS total_completed,
                SUM(CASE WHEN is_sync = 1 AND sync_status = 1 THEN 1 ELSE 0 END) AS total_in_progress,
                SUM(CASE WHEN is_sync = 1 AND sync_status = 2 THEN 1 ELSE 0 END) AS total_awaiting_action,
                SUM(CASE WHEN grade = 1 THEN 1 ELSE 0 END) AS total_grade_a,
                SUM(CASE WHEN grade = 2 THEN 1 ELSE 0 END) AS total_grade_b,
                SUM(CASE WHEN grade = 3 THEN 1 ELSE 0 END) AS total_grade_c,
                SUM(CASE WHEN grade = 4 THEN 1 ELSE 0 END) AS total_grade_d,
                SUM(CASE WHEN grade = 5 THEN 1 ELSE 0 END) AS total_grade_e
            FROM uploaded_files
        """)

        query2 = text("""
            SELECT
                uf.file_id, uf.institution_name, uf.original_filename,
                uf.upload_timestamp, ss.status_code AS sync_status, rg.grade_code AS grade
            FROM uploaded_files uf
            INNER JOIN ref_sync_statuses ss ON ss.sync_status_id = uf.sync_status
            INNER JOIN ref_grades rg ON rg.grade_id = uf.grade
            WHERE uf.is_sync = 1 AND DATE(uf.upload_timestamp) = CURRENT_DATE()
            ORDER BY uf.upload_timestamp DESC
        """)

        with self.engine.begin() as conn:
            summary           = conn.execute(query1).mappings().first()
            recent_sync_files = conn.execute(query2).mappings().all()

        return {
            "summary":           dict(summary) if summary else {},
            "recent_sync_files": [dict(row) for row in recent_sync_files],
        }