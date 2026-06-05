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

        if grade == "A":
            result = self.matching_service.process_grade_a(file_id)
        elif grade == "B":
            result = self.matching_service.process_grade_b(file_id)
        elif grade == "C":
            result = self.matching_service.process_grade_c(file_id)
        elif grade == "D":
            result = self.matching_service.process_grade_d(file_id)
        elif grade == "E":
            result = self.matching_service.process_grade_e(file_id)
        else:
            raise Exception(f"Unsupported grade: {grade}")
        # Trigger Reasoning Celery Task as a background event
        try:
            from reasoning.tasks import process_file_reasoning
            process_file_reasoning.delay(file_id)
            print(f"Enqueued reasoning task for {file_id}")
        except Exception as e:
            print(f"Failed to enqueue reasoning task for {file_id}: {e}")

        return result