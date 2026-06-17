from sqlalchemy import text

class RetrieveRepository:
    def __init__(self, engine):
        self.engine = engine

    def get_graded_files(self, page, page_size):
        """
        Retrieve paginated uploaded file records along with grading and
        processing status information.
        """
        offset = (page - 1) * page_size

        count_query = text("""
            SELECT COUNT(*) AS total
            FROM uploaded_files
        """)

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
            INNER JOIN ref_grades rg
                ON uf.grade = rg.grade_id
            INNER JOIN ref_process rp
                ON uf.processing_status = rp.process_id
            ORDER BY uf.upload_timestamp DESC
            LIMIT :limit
            OFFSET :offset
        """)

        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query).scalar()

            rows = conn.execute(
                data_query,
                {
                    "limit": page_size,
                    "offset": offset
                }
            ).mappings().all()

        return [dict(row) for row in rows], total_rows
    
    def get_synchronized_files(
        self,
        page,
        page_size,
        institution_name,
        grade,
        sync_status
    ):
        """
        Retrieve paginated synchronization file records with optional filtering
        by institution, grade, and synchronization status.
        """
        offset = (page - 1) * page_size

        where_conditions = []
        params = {
            "limit": page_size,
            "offset": offset
        }

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
                uf.file_id,
                uf.original_filename,
                uf.institution_name,
                uf.upload_timestamp,
                rg.grade_code AS grade,
                uf.row_count,
                uf.is_sync,
                rs.status_code AS sync_status
            FROM uploaded_files uf
            JOIN ref_grades rg ON uf.grade = rg.grade_id
            JOIN ref_sync_statuses rs ON uf.sync_status = rs.sync_status_id
            {where_clause}
            ORDER BY uf.upload_timestamp DESC
            LIMIT :limit
            OFFSET :offset
        """)
        

        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query, params).scalar()
            rows = conn.execute(data_query, params).mappings().all()

        return [dict(row) for row in rows], total_rows
    
    def get_history_data(
        self,
        page,
        page_size,
        institution_name,
        start_date,
        end_date
    ):
        """
        Retrieve paginated synchronization history records with summary counts of match,
        manual match, and unmatch statistics.
        """
        offset = (page - 1) * page_size

        where_conditions = []
        params = {
            "limit": page_size,
            "offset": offset
        }

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
            AND uf.sync_status = 1
        """)

        data_query = text(f"""
            SELECT
                uf.file_id,
                uf.institution_name,
                uf.original_filename,
                uf.upload_timestamp,

                SUM(CASE WHEN i.match_result = 1 THEN 1 ELSE 0 END) AS total_auto_match,
                SUM(CASE WHEN i.match_result = 4 THEN 1 ELSE 0 END) AS total_manual_match,
                SUM(CASE WHEN i.match_result IN (3, 5) THEN 1 ELSE 0 END) AS total_unmatch

            FROM uploaded_files uf
            INNER JOIN institution i
                ON i.file_id = uf.file_id

            {where_clause}
            AND uf.sync_status = 1

            GROUP BY
                uf.file_id,
                uf.institution_name,
                uf.original_filename,
                uf.upload_timestamp

            ORDER BY uf.upload_timestamp DESC
            LIMIT :limit
            OFFSET :offset
        """)

        with self.engine.connect() as conn:
            total_rows = conn.execute(count_query, params).scalar()
            rows = conn.execute(data_query, params).mappings().all()

        return [dict(row) for row in rows], total_rows
    
    def get_minio_path(self, file_id: str):
        """
        Retrieve the MinIO path and synchronization state associated with the
        specified file identifier.
        """
        q = text("""
            SELECT minio_path, is_sync, sync_status
            FROM uploaded_files
            WHERE file_id = :file_id
        """)

        with self.engine.connect() as conn:
            return conn.execute(q, {"file_id": file_id}).mappings().first()
        
    def get_completed_data(self, file_id: str):
        """
        Retrieve top matched and unmatched records ordered by match score for the specified file.
        """
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
            matches = conn.execute(
                match_query,
                {"file_id": file_id}
            ).mappings().all()

            unmatches = conn.execute(
                unmatch_query,
                {"file_id": file_id}
            ).mappings().all()

        return {
            "match": [dict(row) for row in matches],
            "unmatch": [dict(row) for row in unmatches]
        }
        
    def get_manual_review_data(self, file_id: str, page, page_size):
        """
        Retrieve paginated institution records that require manual review for a
        specific synchronization file, including match details and review reasons.
        """

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
            total_rows = conn.execute(count_query,{"file_id": file_id}).scalar()
            rows = conn.execute(
                manual_review_query,
                {
                    "file_id": file_id,
                    "limit": page_size,
                    "offset": offset
                }
            ).mappings().all()

        return [dict(row) for row in rows], total_rows
        
    def get_master_by_niks(self, niks):
        """
        Retrieve master records for the specified NIKs and return them as a
        dictionary keyed by NIK.
        """
        if not niks:
            return {}

        q = text("""
            SELECT nik, nama_lengkap, tempat_lahir, tanggal_lahir, jenis_kelamin, nama_ibu, provinsi, kabupaten, kecamatan, kelurahan, status_kematian
            FROM master
            WHERE nik IN :niks
        """)

        with self.engine.connect() as conn:
            rows = conn.execute(q, {"niks": tuple(niks)}).mappings().all()

        return {r["nik"]: dict(r) for r in rows}
    
    def mark_manual_match(self, id_incoming, file_id):
        query = text("""
            UPDATE institution
            SET match_result = 4
            WHERE id_incoming = :id_incoming
            AND file_id = :file_id
        """)

        with self.engine.begin() as conn:
            result = conn.execute(
                query,
                {
                    "id_incoming": id_incoming,
                    "file_id": file_id
                }
            )

        return result.rowcount
    
    def mark_manual_unmatch(self, id_incoming, file_id):
        query = text("""
            UPDATE institution
            SET match_result = 5
            WHERE id_incoming = :id_incoming
            AND file_id = :file_id
        """)

        with self.engine.begin() as conn:
            result = conn.execute(
                query,
                {
                    "id_incoming": id_incoming,
                    "file_id": file_id
                }
            )

        return result.rowcount
    
    def mark_as_completed(self, file_id):
        query1 = text("""
            UPDATE institution
            SET match_result = 5
            WHERE match_result = 2
            AND file_id = :file_id
        """)

        query2 = text("""
            UPDATE uploaded_files
            SET sync_status = 3
            WHERE file_id = :file_id
        """)

        with self.engine.begin() as conn:
            r1 = conn.execute(query1, {"file_id": file_id})
            r2 = conn.execute(query2, {"file_id": file_id})

        return {
            "institution_updated": r1.rowcount,
            "file_updated": r2.rowcount
        }