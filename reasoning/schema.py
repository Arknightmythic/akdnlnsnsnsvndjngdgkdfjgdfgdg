from pydantic import BaseModel, Field

class ReasoningOutput(BaseModel):
    reason: str = Field(description="Penjelasan singkat dalam Bahasa Indonesia mengenai perbedaan datanya secara padat dan jelas.")
