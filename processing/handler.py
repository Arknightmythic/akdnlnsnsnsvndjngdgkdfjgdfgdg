from .matching_service import MatchingService
from .matching_service_new import MatchingServiceV2

class MatchFileHandler:

    def __init__(self, minio_client, bucket_name, starrocks_engine, grade_rules):

        self.matching_service = MatchingService(
            engine=starrocks_engine,
            minio_client=minio_client,
            bucket_name=bucket_name,
            grade_rules=grade_rules
        )

        self.matching_service_new = MatchingServiceV2(
            engine=starrocks_engine,
            minio_client=minio_client,
            bucket_name=bucket_name,
            grade_rules=grade_rules
        )

    def process_file(self, file_id: str):
        print("Processing data...")

        uploaded_file = self.matching_service.starrocks_service.get_uploaded_file(file_id)

        if not uploaded_file:
            raise Exception("File ID not found")

        grade = uploaded_file["grade"]

        if grade == 6:
            if not uploaded_file.get("is_custom_ready"):
                raise Exception(
                    "Custom field mapping belum dikonfirmasi user "
                    "(is_custom_ready=0) — matching tidak bisa dijalankan."
                )
            result = self.matching_service_new.process_custom_matching_job(file_id)
        elif 1 <= grade <= 5:
            result = self.matching_service_new.process_matching_job(file_id, grade)
        else:
            raise Exception(f"Unsupported grade: {grade}")

        return result