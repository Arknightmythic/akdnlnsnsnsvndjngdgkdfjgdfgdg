from rapidfuzz.distance import JaroWinkler

class ScoringService:

    def __init__(self):
        print("Scoring Service Initiated!")

    def safe_jaro(self, left, right):
        if left is None or right is None:
            return 0
        
        left = str(left)
        right = str(right)

        if not left or not right:
            return 0

        return JaroWinkler.similarity(left, right)
    
    def compute_similarity_score(self, grade,
        b_nama=None, a_nama=None,
        b_tempat_lahir=None, a_tempat_lahir=None,
        b_tanggal_lahir=None, a_tanggal_lahir=None,
        b_provinsi=None, a_provinsi=None,
        b_kabupaten=None, a_kabupaten=None,
        b_kecamatan=None, a_kecamatan=None,
        b_kelurahan=None, a_kelurahan=None,
        b_nama_ibu=None, a_nama_ibu=None
        ):
        if grade == 1:
            return (
                self.safe_jaro(b_nama, a_nama)
            ) * 100
        elif grade == 2:
            return (
                self.safe_jaro(b_nama, a_nama) * 0.8 +
                self.safe_jaro(b_tempat_lahir, a_tempat_lahir) * 0.1 +
                self.safe_jaro(b_nama_ibu, a_nama_ibu) * 0.1
            ) * 100
        elif grade == 3:
            return (
                self.safe_jaro(b_nama, a_nama) * 0.6 +
                self.safe_jaro(b_tempat_lahir, a_tempat_lahir) * 0.2 +
                self.safe_jaro(b_tanggal_lahir, a_tanggal_lahir) * 0.2
            )
        elif grade == 4:
            return (
                self.safe_jaro(b_nama, a_nama) * 0.6 +
                self.safe_jaro(b_tempat_lahir, a_tempat_lahir) * 0.05 +
                self.safe_jaro(b_nama_ibu, a_nama_ibu) * 0.05 +
                self.safe_jaro(b_tanggal_lahir, a_tanggal_lahir) * 0.3
            ) * 100
        elif grade == 5:
            area_scores = []

            if (b_provinsi and a_provinsi):
                area_scores.append(self.safe_jaro(b_provinsi, a_provinsi))
            if (b_kabupaten and a_kabupaten):
                area_scores.append(self.safe_jaro(b_kabupaten, a_kabupaten))
            if (b_kecamatan and a_kecamatan):
                area_scores.append(self.safe_jaro(b_provinsi, a_provinsi))
            if (b_kelurahan and a_kelurahan):
                area_scores.append(self.safe_jaro(b_provinsi, a_provinsi))

            if len(area_scores) > 0:
                area_score = (sum(area_scores) / len(area_scores))

            return (
                self.safe_jaro(b_nama, a_nama) * 0.5 +
                area_score * 0.3 +
                self.safe_jaro(b_nama_ibu, a_nama_ibu) * 0.01 +
                self.safe_jaro(b_tanggal_lahir, a_tanggal_lahir) * 0.1
            ) * 100
