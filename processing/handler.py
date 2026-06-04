from .matching_service import MatchingService

class MatchFileHandler:

    def __init__(self, minio_client, bucket_name, starrocks_engine):

        self.matching_service = MatchingService(
            engine=starrocks_engine,
            minio_client=minio_client,
            bucket_name=bucket_name
        )

        print("Match Handler Initialized")

    async def process_file(self, file_id: str):
        print("Processing data...")

        uploaded_file = self.matching_service.starrocks_service.get_uploaded_file(file_id)

        if not uploaded_file:
            raise Exception("File ID not found")

        grade = uploaded_file["grade"]

        if grade == 1:
            return self.matching_service.process_grade_a(
                file_id
            )

        if grade == 2:
            return self.matching_service.process_grade_b(
                file_id
            )
        
        if grade == 3:
            return self.matching_service.process_grade_c(
                file_id
            )
        
        if grade == 4:
            return self.matching_service.process_grade_d(
                file_id
            )
        
        if grade == 5:
            return self.matching_service.process_grade_e(
                file_id
            )

        raise Exception(f"Unsupported grade: {grade}")