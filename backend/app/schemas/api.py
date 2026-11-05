from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Classification = Literal["ASBESTOS_CONTAINING", "NON_ASBESTOS", "MANUAL_REVIEW"]


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    page: int
    source_text: str
    normalized_name: str
    classification: str
    confidence: float
    bbox: str
    engine: str


class ProcessIn(BaseModel):
    engine: Literal["easyocr", "paddleocr", "auto"] = "easyocr"
    denoise: bool = False
    contrast: bool = False
    threshold: bool = False


class MaterialIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    standard_name: str = Field(min_length=2, max_length=255)
    aliases: str = Field(default="", max_length=4000)
    category: str = Field(default="Unknown", max_length=100)
    description: str = Field(default="", max_length=4000)
    manufacturer: str = Field(default="", max_length=255)
    asbestos_status: Literal[
        "CONTAINS_ASBESTOS",
        "DOES_NOT_CONTAIN_ASBESTOS",
        "UNKNOWN",
        "CONDITION_DEPENDENT",
    ] = "UNKNOWN"
    conditions: str = Field(default="", max_length=4000)
    source: str = Field(default="", max_length=4000)
    verification_status: Literal["UNVERIFIED", "VERIFIED", "DEMONSTRATION"] = (
        "UNVERIFIED"
    )

    @model_validator(mode="after")
    def verify_source(self):
        if self.verification_status == "VERIFIED" and len(self.source.strip()) < 10:
            raise ValueError("Verified records require a documented reference source")
        return self


class ReviewIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    finding_id: int = Field(gt=0)
    classification: Classification
    reason: str = Field(min_length=10, max_length=4000)
    source: str = Field(min_length=10, max_length=4000)


class CompareIn(BaseModel):
    document_id: int = Field(gt=0)


class LoginIn(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=1000)
