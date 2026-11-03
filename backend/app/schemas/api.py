from datetime import datetime
from pydantic import BaseModel, ConfigDict

class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int; page: int; source_text: str; normalized_name: str; classification: str; confidence: float; bbox: str; engine: str

class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int; filename: str; content_type: str; pages: int; status: str; created_at: datetime
    findings: list[FindingOut] = []
