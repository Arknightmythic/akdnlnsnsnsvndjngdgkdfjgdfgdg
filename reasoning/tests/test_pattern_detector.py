import pytest
from reasoning.pattern_detector import PatternDetector

def test_pattern_detection():
    detector = PatternDetector()
    
    # 1. Test semua sama
    incoming = {
        "nama_lengkap": "Budi",
        "tempat_lahir": "Jakarta",
        "tanggal_lahir": "1990-01-01",
        "jenis_kelamin": "L",
        "nama_ibu": "Siti"
    }
    master = {
        "master_nama_lengkap": "budi",
        "master_tempat_lahir": "jakarta",
        "master_tanggal_lahir": "1990-01-01",
        "master_jenis_kelamin": "Laki-laki",
        "master_nama_ibu": "siti"
    }
    
    res = detector.detect(incoming, master)
    assert res["pattern_name_suffix"] == "SEMUA_SAMA"
    for k, v in res["statuses"].items():
        assert v == "SAMA"
        
    # 2. Test nama beda dan tanggal lahir kosong
    incoming["nama_lengkap"] = "Budi Santoso"
    incoming["tanggal_lahir"] = None
    
    res = detector.detect(incoming, master)
    assert "NAMA_BEDA" in res["pattern_name_suffix"]
    assert "TGLLAHIR_KOSONG" in res["pattern_name_suffix"]
    assert res["statuses"]["nama_lengkap"] == "BEDA"
    assert res["statuses"]["tanggal_lahir"] == "KOSONG_INCOMING"

if __name__ == "__main__":
    test_pattern_detection()
    print("Pattern detector tests passed!")
