import polars as pl
import tempfile
from sqlalchemy import text
from io import BytesIO

class ObjectStorageService:
    def __init__ (self, minio_client, bucket_name):
        self.minio_client = minio_client
        self.bucket_name = bucket_name
    
    def load_parquet_from_minio(self, object_name, column_rename_map: dict | None = None):
        response = self.minio_client.get_object(
            self.bucket_name,
            object_name
        )

        with tempfile.NamedTemporaryFile(suffix=".parquet") as tmp:
            for chunk in response.stream(32 * 1024):
                tmp.write(chunk)
            tmp.flush()
            df = pl.read_parquet(tmp.name)

        df.columns = [c.strip().lower()for c in df.columns]
        if column_rename_map:
            normalized_map = {k.strip().lower(): v for k, v in column_rename_map.items()}
            df = df.rename({
                old: new for old, new in normalized_map.items() if old in df.columns
            })

        expressions = []
        if "id" in df.columns:
            expressions.append(
                pl.col("id")
                    .cast(pl.Utf8)
                    .str.strip_chars()
            )

        if "nik" in df.columns:
            expressions.append(
                pl.col("nik")
                    .cast(pl.Utf8)
                    .str.strip_chars()
            )

        if "nama" in df.columns:
            expressions.append(
                pl.col("nama")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("nama_clean")
            )

        if "tempat_lahir" in df.columns:
            expressions.append(
                pl.col("tempat_lahir")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("tempat_lahir_clean")
            )

        if "provinsi" in df.columns:
            expressions.append(
                pl.col("provinsi")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("provinsi_clean")
            )

        if "kabupaten" in df.columns:
            expressions.append(
                pl.col("kabupaten")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("kabupaten_clean")
            )

        if "kecamatan" in df.columns:
            expressions.append(
                pl.col("kecamatan")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("kecamatan_clean")
            )

        if "kelurahan" in df.columns:
            expressions.append(
                pl.col("kelurahan")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("kelurahan_clean")
            )

        if "tanggal_lahir" in df.columns:
            raw_tanggal = (
                pl.col("tanggal_lahir")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
            )

            expressions.append(

                pl.coalesce([
                    raw_tanggal.str.strptime(
                        pl.Date,
                        format="%d/%m/%Y",
                        strict=False
                    ),
                    raw_tanggal.str.strptime(
                        pl.Date,
                        format="%d-%m-%Y",
                        strict=False
                    ),
                    raw_tanggal.str.strptime(
                        pl.Date,
                        format="%d %m %Y",
                        strict=False
                    ),
                    raw_tanggal.str.strptime(
                        pl.Date,
                        format="%d-%b-%Y",
                        strict=False
                    ),
                    raw_tanggal.str.strptime(
                        pl.Date,
                        format="%d %B %Y",
                        strict=False
                    ),
                    raw_tanggal.str.strptime(
                        pl.Date,
                        format="%Y-%m-%d",
                        strict=False
                    )

                ])
                .alias("tanggal_lahir_clean")
            )

        if "jenis_kelamin" in df.columns:
            expressions.append(
                pl.when(
                    pl.col("jenis_kelamin")
                        .cast(pl.Utf8)
                        .str.to_lowercase()
                        .str.strip_chars()
                        .is_in([
                            "laki-laki",
                            "laki laki",
                            "pria",
                            "male",
                            "l"
                        ])
                )
                .then(pl.lit("l"))

                .when(
                    pl.col("jenis_kelamin")
                        .cast(pl.Utf8)
                        .str.to_lowercase()
                        .str.strip_chars()
                        .is_in([
                            "perempuan",
                            "wanita",
                            "female",
                            "p"
                        ])
                )
                .then(pl.lit("p"))
                .otherwise(None)
                .alias("jenis_kelamin_clean")
            )

        if "status_hidup" in df.columns:
            expressions.append(
                pl.when(
                    pl.col("status_hidup")
                        .cast(pl.Utf8)
                        .str.to_lowercase()
                        .str.strip_chars()
                        .is_in([
                            "hidup",
                            "h"
                        ])
                )
                .then(pl.lit("h"))
                .when(
                    pl.col("status_hidup")
                        .cast(pl.Utf8)
                        .str.to_lowercase()
                        .str.strip_chars()
                        .is_in([
                            "meninggal",
                            "mati",
                            "wafat",
                            "m"
                        ])
                )
                .then(pl.lit("m"))
                .otherwise(None)
                .alias("status_hidup_clean")
            )

        if "nama_ibu" in df.columns:
            expressions.append(
                pl.col("nama_ibu")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .alias("nama_ibu_clean")
            )

        df = df.with_columns(expressions)

        # Guard: tanggal_lahir_clean cuma ada kalau kolom "tanggal_lahir" tadinya
        # ada di file incoming (lihat blok kondisional di atas). Tanpa guard ini,
        # file grade 1/2 (tanpa tanggal_lahir) atau grade 6 yang tidak memasangkan
        # tanggal_lahir akan crash ColumnNotFoundError (BUG_FIXING_GUIDE.md #5).
        if "tanggal_lahir_clean" in df.columns:
            df = df.with_columns(
                pl.when(
                    pl.col("tanggal_lahir_clean")
                        .dt.year()
                        < 1900
                )
                .then(None)
                .otherwise(
                    pl.col("tanggal_lahir_clean")
                )
                .alias("tanggal_lahir_clean")
            )

        return df