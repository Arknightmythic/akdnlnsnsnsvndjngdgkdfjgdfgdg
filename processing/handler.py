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

        print("Match Handler Initialized")

    def process_file(self, file_id: str):
        print("Processing data...")

        uploaded_file = self.matching_service.starrocks_service.get_uploaded_file(file_id)

        if not uploaded_file:
            raise Exception("File ID not found")

        grade = uploaded_file["grade"]

        if grade < 1 or grade > 5:
            raise Exception(f"Unsupported grade: {grade}")
        
        result = self.matching_service_new.process_matching_job(file_id, grade)

        return result