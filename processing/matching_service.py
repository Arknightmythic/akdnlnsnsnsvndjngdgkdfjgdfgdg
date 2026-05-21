from io import BytesIO

import polars as pl
from rapidfuzz.distance import JaroWinkler
from sqlalchemy import text


class MatchingService:

    def __init__(self, engine, minio_client, bucket_name):
        self.engine = engine
        self.minio_client = minio_client
        self.bucket_name = bucket_name

    def normalize_string(self, value):
        if value is None:
            return ""

        return (
            str(value)
            .strip()
            .lower()
        )

    def get_uploaded_file(self, file_id):

        query = text("""
            SELECT
                file_id,
                minio_path,
                upload_timestamp,
                grade
            FROM uploaded_files
            WHERE file_id = :file_id
        """)

        with self.engine.connect() as conn:
            result = conn.execute(
                query,
                {"file_id": file_id}
            ).mappings().first()

        return result

    def load_csv_from_minio(self, object_name):

        response = self.minio_client.get_object(
            self.bucket_name,
            object_name
        )

        file_bytes = response.read()

        df = pl.read_csv(BytesIO(file_bytes))

        df.columns = [
            c.strip().lower()
            for c in df.columns
        ]

        return df

    def fetch_master_by_nik(self,  conn, nik):

        query = text("""
            SELECT
                nik,
                nama_lengkap
            FROM master
            WHERE nik = :nik
            LIMIT 1
        """)

        result = conn.execute(
            query,
            {"nik": nik}
        ).mappings().first()

        return result

    def insert_result(
        self,
        conn,
        nik_incoming,
        nik_master,
        file_id,
        score,
        match_result,
        upload_date
    ):

        query = text("""
            INSERT INTO institution (
                nik_incoming,
                nik_master,
                file_id,
                match_score,
                match_result,
                upload_date
            )
            VALUES (
                :nik_incoming,
                :nik_master,
                :file_id,
                :match_score,
                :match_result,
                :upload_date
            )
        """)

        conn.execute(query, {
            "nik_incoming": nik_incoming,
            "nik_master": nik_master,
            "file_id": file_id,
            "match_score": score,
            "match_result": match_result,
            "upload_date": upload_date
        })

    def process_grade_a(self, file_id):

        uploaded_file = self.get_uploaded_file(file_id)

        if not uploaded_file:
            raise Exception("File ID not found")

        if uploaded_file["grade"] != "A":
            raise Exception("This endpoint only processes Grade A files")

        df = self.load_csv_from_minio(
            uploaded_file["minio_path"]
        )

        with self.engine.begin() as conn:

            for row in df.iter_rows(named=True):

                nik = str(row["nik"]).strip()

                print("Checking master table...")
                existing_record = self.fetch_master_by_nik(
                    conn=conn,
                    nik=nik
                )

                if not existing_record:
                    print("Nothing matched from master!")
                    self.insert_result(
                        nik_incoming=nik,
                        nik_master=None,
                        conn=conn,
                        file_id=file_id,
                        score=0,
                        match_result="NO_NIK_MATCH",
                        upload_date=uploaded_file["upload_timestamp"]
                    )

                    continue

                print("Match found!")
                incoming_name = self.normalize_string(
                    row["nama"]
                )

                existing_name = self.normalize_string(
                    existing_record["nama_lengkap"]
                )

                score = JaroWinkler.similarity(
                    incoming_name,
                    existing_name
                )

                score = round(score * 100, 2)

                if score >= 85:
                    result = "MATCHED"
                else:
                    result = "LOW_NAME_SIMILARITY"

                print("Inserting institution...")
                self.insert_result(
                    nik_incoming=nik,
                    nik_master=existing_record["nik"],
                    conn=conn,
                    file_id=file_id,
                    score=score,
                    match_result=result,
                    upload_date=uploaded_file["upload_timestamp"]
                )