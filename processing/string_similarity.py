from rapidfuzz.distance import JaroWinkler

class ScoringService:

    def __init__(self):
        print("Scoring Service Initiated!")

    def safe_jaro(self, left, right):
        if not left or not right:
            return 0

        return JaroWinkler.similarity(left, right)

    def compute_similarity_matched_grade_B(self, 
        b_nama, a_nama,
        b_tempat_lahir, a_tempat_lahir,
        b_nama_ibu, a_nama_ibu
        ):

        return (
            self.safe_jaro(b_nama, a_nama) * 0.8 +
            self.safe_jaro(b_tempat_lahir, a_tempat_lahir) * 0.1 +
            self.safe_jaro(b_nama_ibu, a_nama_ibu) * 0.1
        ) * 100