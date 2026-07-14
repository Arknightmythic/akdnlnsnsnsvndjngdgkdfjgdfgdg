from typing import List
from pydantic import BaseModel, Field


class FieldPair(BaseModel):
    master_column: str = Field(
        description=(
            "Nama kolom pada tabel master. HARUS persis salah satu dari daftar "
            "MASTER COLUMNS yang diberikan, tanpa modifikasi."
        )
    )
    incoming_column: str = Field(
        description=(
            "Nama kolom pada file custom (incoming) yang paling sesuai dipasangkan "
            "dengan master_column. HARUS persis salah satu dari daftar INCOMING "
            "COLUMNS yang diberikan, tanpa modifikasi."
        )
    )
    confidence: float = Field(
        description=(
            "Skor keyakinan pairing ini benar, antara 0.0 (sangat tidak yakin) "
            "sampai 1.0 (sangat yakin)."
        ),
        ge=0.0,
        le=1.0,
    )


class FieldMappingOutput(BaseModel):
    pairs: List[FieldPair] = Field(
        description=(
            "Daftar pairing master_column <-> incoming_column yang berhasil "
            "diidentifikasi. Kolom master yang tidak punya padanan masuk akal "
            "di incoming TIDAK perlu dimasukkan ke daftar ini."
        )
    )