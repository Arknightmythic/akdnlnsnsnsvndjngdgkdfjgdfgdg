import hashlib

class PatternDetector:
    def __init__(self):
        # Definisikan mapping kolom incoming dan master
        self.fields = [
            ("nama_lengkap", "nama_lengkap", "master_nama_lengkap", "NAMA"),
            ("tempat_lahir", "tempat_lahir", "master_tempat_lahir", "TMPTLAHIR"),
            ("tanggal_lahir", "tanggal_lahir", "master_tanggal_lahir", "TGLLAHIR"),
            ("jenis_kelamin", "jenis_kelamin", "master_jenis_kelamin", "GENDER"),
            ("nama_ibu", "nama_ibu", "master_nama_ibu", "IBU"),
        ]

    def _is_empty(self, val):
        if val is None:
            return True
        v = str(val).strip().lower()
        if v in ["", "null", "none"]:
            return True
        return False

    def _clean_gender(self, val):
        if self._is_empty(val):
            return ""
        v = str(val).strip().lower()
        if v in ["l", "laki-laki", "pria"]:
            return "l"
        if v in ["p", "perempuan", "wanita"]:
            return "p"
        return v

    def detect(self, incoming_row, master_row=None):
        """
        Mendeteksi pola perbedaan antara incoming_row dan master_row.
        Bisa menerima 1 parameter dict (jika sudah di-join) atau 2 dict terpisah.
        """
        if master_row is None:
            # Asumsi row sudah digabung (hasil DuckDB join)
            row = incoming_row
        else:
            # Asumsi 2 dict terpisah
            row = {**incoming_row, **master_row}

        statuses = {}
        name_parts = []

        for field_name, inc_col, mst_col, short_name in self.fields:
            inc_val = row.get(inc_col)
            mst_val = row.get(mst_col)

            inc_empty = self._is_empty(inc_val)
            mst_empty = self._is_empty(mst_val)

            status = "SAMA"
            if inc_empty and mst_empty:
                status = "SAMA" # Keduanya kosong dianggap sama/tidak ada masalah perbandingan
            elif inc_empty:
                status = "KOSONG_INCOMING"
                name_parts.append(f"{short_name}_KOSONG")
            elif mst_empty:
                status = "KOSONG_MASTER"
                name_parts.append(f"{short_name}_KOSONG_MASTER")
            else:
                # Keduanya ada nilainya, bandingkan
                val1 = str(inc_val).strip().lower()
                val2 = str(mst_val).strip().lower()
                
                # Normalisasi khusus gender
                if field_name == "jenis_kelamin":
                    val1 = self._clean_gender(val1)
                    val2 = self._clean_gender(val2)
                    
                if val1 != val2:
                    status = "BEDA"
                    name_parts.append(f"{short_name}_BEDA")
                else:
                    status = "SAMA"

            statuses[field_name] = status

        # Generate Signature
        # Urutkan berdasarkan field_name agar konsisten
        signature_parts = []
        for field_name in sorted(statuses.keys()):
            signature_parts.append(f"{field_name}:{statuses[field_name]}")
            
        pattern_signature = "|".join(signature_parts)
        
        # Generate Hash
        pattern_hash = hashlib.sha256(pattern_signature.encode('utf-8')).hexdigest()
        
        # Generate Name Suffix
        pattern_name_suffix = "__".join(name_parts)
        if not pattern_name_suffix:
            pattern_name_suffix = "SEMUA_SAMA"
            
        return {
            "pattern_hash": pattern_hash,
            "pattern_signature": pattern_signature,
            "pattern_name_suffix": pattern_name_suffix,
            "statuses": statuses
        }
