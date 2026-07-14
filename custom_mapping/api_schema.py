from typing import List, Optional
from pydantic import BaseModel, Field


class PairInput(BaseModel):
    master_column: str
    incoming_column: str
    weight: float = Field(ge=0.0, le=1.0)


class SaveMappingRequest(BaseModel):
    pairs: List[PairInput]


class PairOutput(BaseModel):
    id: Optional[int] = None
    master_column: str
    incoming_column: str
    weight: Optional[float] = None
    confidence: Optional[float] = None
    source: str


class MappingStatusResponse(BaseModel):
    file_id: str
    grade: Optional[int] = None
    is_custom_ready: bool
    custom_mapping_task_status: str
    incoming_columns: List[str]
    master_columns: List[str]
    pairs: List[PairOutput]