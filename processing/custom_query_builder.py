
MASTER_COLUMN_CLEAN_BASE = {
    "nik": None,
    "nama_lengkap": "nama",
    "tempat_lahir": "tempat_lahir",
    "tanggal_lahir": "tanggal_lahir",
    "jenis_kelamin": "jenis_kelamin",
    "nama_ibu": "nama_ibu",
    "provinsi": "provinsi",
    "kabupaten": "kabupaten",
    "kecamatan": "kecamatan",
    "kelurahan": "kelurahan",
}

# Field yang boleh dipakai sebagai anchor blocking kalau NIK gak tersedia di
# pairing, meniru pola grade 3 (jenis_kelamin exact + prefix nama + tanggal
# day/month).
BLOCKING_ANCHOR_FIELDS = ["jenis_kelamin", "nama_lengkap", "tanggal_lahir"]


def resolve_clean_base(master_column: str) -> str | None:
    return MASTER_COLUMN_CLEAN_BASE.get(master_column, master_column)


def build_incoming_rename_map(active_pairs: list[dict]) -> dict:
    """
    Rename kolom incoming (nama asli bebas di file custom) -> nama kolom
    "role" yang dikenali ObjectStorageService.load_parquet_from_minio (nik,
    nama, tempat_lahir, dst), supaya cleaning logic yang sudah ada bisa
    dipakai APA ADANYA tanpa modifikasi untuk grade 6.

    active_pairs: [{"master_column": "tanggal_lahir", "incoming_column": "b", ...}, ...]
    """
    rename_map = {}
    for pair in active_pairs:
        master_col = pair["master_column"]
        if master_col == "nik":
            target = "nik"
        else:
            target = MASTER_COLUMN_CLEAN_BASE.get(master_col, master_col)
        rename_map[pair["incoming_column"]] = target
    return rename_map


def build_dynamic_matching_query(active_pairs: list[dict]) -> str:
    """
    active_pairs: [{"master_column": "tanggal_lahir", "weight": 0.3}, ...]

    Raises ValueError kalau tidak ada field yang cukup kuat buat dipakai
    sebagai blocking anchor (nik / jenis_kelamin / nama_lengkap /
    tanggal_lahir semuanya tidak ada di pairing) — supaya matching tidak
    diam-diam jatuh ke full cross join yang mahal & berisiko timeout untuk
    file besar. Idealnya ini dicegah lebih awal, saat user save weight
    (validasi di endpoint), bukan baru ketahuan di sini.
    """
    paired_master_cols = {p["master_column"] for p in active_pairs}

    select_cols = ["i.id AS incoming_row_id", "m.nik AS nik_master"]
    for master_col in paired_master_cols:
        if master_col == "nik":
            continue  # nik gak punya _clean, dan udah kepilih via nik_master di atas
        clean_base = resolve_clean_base(master_col)
        select_cols.append(f"i.{clean_base}_clean")
        select_cols.append(f"m.{clean_base}_master_clean")
    select_clause = ",\n        ".join(select_cols)

    if "nik" in paired_master_cols:
        join_condition = "i.nik = m.nik"
    else:
        conditions = []
        for anchor in BLOCKING_ANCHOR_FIELDS:
            if anchor not in paired_master_cols:
                continue
            clean_base = resolve_clean_base(anchor)

            if anchor == "jenis_kelamin":
                conditions.append(
                    f"i.{clean_base}_clean = m.{clean_base}_master_clean"
                )
            elif anchor == "nama_lengkap":
                conditions.append(
                    f"i.{clean_base}_clean IS NOT NULL AND m.{clean_base}_master_clean IS NOT NULL\n"
                    f"            AND LEFT(i.{clean_base}_clean, 3) = LEFT(m.{clean_base}_master_clean, 3)"
                )
            elif anchor == "tanggal_lahir":
                conditions.append(
                    f"i.{clean_base}_clean IS NOT NULL AND m.{clean_base}_master_clean IS NOT NULL\n"
                    f"            AND EXTRACT(DAY FROM CAST(i.{clean_base}_clean AS DATE)) = EXTRACT(DAY FROM CAST(m.{clean_base}_master_clean AS DATE))\n"
                    f"            AND EXTRACT(MONTH FROM CAST(i.{clean_base}_clean AS DATE)) = EXTRACT(MONTH FROM CAST(m.{clean_base}_master_clean AS DATE))"
                )

        if not conditions:
            raise ValueError(
                "Pairing custom butuh minimal salah satu dari: nik, jenis_kelamin, "
                "nama_lengkap, atau tanggal_lahir sebagai anchor blocking, supaya "
                "matching tidak jatuh ke full cross join yang mahal."
            )

        join_condition = "\n            AND ".join(conditions)

    return f"""
        SELECT
        {select_clause}
        FROM incoming_df i
        INNER JOIN master_df m
            ON {join_condition}
    """