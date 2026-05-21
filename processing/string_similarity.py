import jellyfish

def jaro_score(a, b):
    if a is None or b is None:
        return 0.0
    return float(jellyfish.jaro_winkler_similarity(str(a), str(b)))

def compute_similarity_matched(b_nama, a_nama, b_tempat_lahir, a_tempat_lahir, b_nama_ibu, a_nama_ibu):

    return (
        jaro_score(b_nama, a_nama) * 0.8 +
        jaro_score(b_tempat_lahir, a_tempat_lahir) * 0.1 +
        jaro_score(b_nama_ibu, a_nama_ibu) * 0.1
    )

def compute_similarity_unmatched(b_nama, a_nama, b_tempat_lahir, a_tempat_lahir, b_nama_ibu, a_nama_ibu):

    return (
        jaro_score(b_nama, a_nama) * 0.8 +
        jaro_score(b_tempat_lahir, a_tempat_lahir) * 0.1 +
        jaro_score(b_nama_ibu, a_nama_ibu) * 0.1
    )

def compute_similarity_data_d(b_nama, a_nama, b_tempat_lahir, a_tempat_lahir, b_tanggal_lahir, a_tanggal_lahir, b_nama_ibu, a_nama_ibu):

        return (
            jaro_score(b_nama, a_nama) * 0.60 +
            jaro_score(b_tempat_lahir, a_tempat_lahir) * 0.05 +
            jaro_score(b_tanggal_lahir, a_tanggal_lahir) * 0.30 +
            jaro_score(b_nama_ibu, a_nama_ibu) * 0.05
        )