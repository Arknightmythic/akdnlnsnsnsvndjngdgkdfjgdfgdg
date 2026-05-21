from .matching_service import MatchingService

class MatchFileHandler:

    def __init__(
        self,
        minio_client,
        bucket_name,
        starrocks_engine
    ):

        self.matching_service = MatchingService(
            engine=starrocks_engine,
            minio_client=minio_client,
            bucket_name=bucket_name
        )

        print("Match Handler Initialized")

    async def process_file(self, file_id: str):
        print("Processing data...")

        results = self.matching_service.process_grade_a(
            file_id=file_id
        )

        print("Processing complete!")
        return {
            "message": "Matching completed",
            "file_id": file_id,
            "results": results
        }