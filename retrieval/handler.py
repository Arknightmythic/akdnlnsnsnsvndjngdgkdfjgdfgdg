from .repository import RetrieveRepository

class RetrieveDataHandler:
    PAGE_SIZE_GRADED = 10
    PAGE_SIZE_SYNCHRONIZED = 15

    def __init__(self, engine):
        self.repository = RetrieveRepository(engine)

    def get_graded_files(self, page):
        data, total_rows = self.repository.get_graded_files(
            page=page,
            page_size=self.PAGE_SIZE_GRADED
        )

        total_pages = (total_rows + self.PAGE_SIZE_GRADED - 1) // self.PAGE_SIZE_GRADED

        return {
            "page": page,
            "page_size": self.PAGE_SIZE_GRADED,
            "total_rows": total_rows,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
            "data": data
        }
    

    def get_synchronized_files(
        self,
        page,
        institution_name,
        grade,
        sync_status
    ):
        data, total_rows = self.repository.get_synchronized_files(
            page=page,
            page_size=self.PAGE_SIZE_SYNCHRONIZED,
            institution_name=institution_name,
            grade=grade,
            sync_status=sync_status
        )

        total_pages = (
            total_rows + self.PAGE_SIZE_SYNCHRONIZED - 1
        ) // self.PAGE_SIZE_SYNCHRONIZED

        return {
            "page": page,
            "page_size": self.PAGE_SIZE_SYNCHRONIZED,
            "total_rows": total_rows,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "data": data
        }
    
    def get_history_data(
        self,
        page,
        institution_name,
        start_date,
        end_date
    ):
        data, total_rows = self.repository.get_history_data(
            page=page,
            page_size=self.PAGE_SIZE_SYNCHRONIZED,
            institution_name=institution_name,
            start_date=start_date,
            end_date=end_date
        )

        for row in data:
            total_records = (
                row["total_auto_match"]
                + row["total_manual_match"]
                + row["total_unmatch"]
            )

            row["percentage_unmatch"] = (
                round((row["total_unmatch"] / total_records) * 100, 2)
                if total_records > 0
                else 0
            )

        total_pages = (
            total_rows + self.PAGE_SIZE_SYNCHRONIZED - 1
        ) // self.PAGE_SIZE_SYNCHRONIZED

        return {
            "page": page,
            "page_size": self.PAGE_SIZE_SYNCHRONIZED,
            "total_rows": total_rows,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "data": data
        }
    
