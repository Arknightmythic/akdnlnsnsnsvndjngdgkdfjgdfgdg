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