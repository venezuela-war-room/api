import re
import unicodedata
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _clean_str(v: str) -> str:
    v = unicodedata.normalize("NFKC", v)
    v = re.sub(r"[\x00-\x1f\x7f]", "", v)
    return " ".join(v.split())


# ── Shared validators ──────────────────────────────────────────────────────────

CleanStr = Annotated[str, Field(min_length=1, max_length=500)]


class _BaseClean(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _strip_strings(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: _clean_str(v) if isinstance(v, str) else v for k, v in data.items()}
        return data


# ── Person schemas ─────────────────────────────────────────────────────────────

class PersonCreate(_BaseClean):
    full_name: str = Field(min_length=2, max_length=200)
    document_id: str | None = Field(default=None, min_length=1, max_length=12)
    age: int | None = Field(default=None, ge=0, le=150)
    hospital: str | None = Field(default=None, min_length=2, max_length=300)
    servicio: str | None = Field(default=None, min_length=1, max_length=300)
    lugar_procedencia: str | None = Field(default=None, min_length=1, max_length=300)
    relevant_info: str | None = Field(default=None, max_length=5000)
    source_url: str | None = Field(default=None, max_length=2000)
    source_hash: str | None = Field(default=None, min_length=8, max_length=128)
    status: str = Field(default="verified")
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, v: str | None) -> str | None:
        if v is not None:
            digits = re.sub(r"\D", "", v)
            if not digits:
                raise ValueError("document_id must contain digits")
            return digits
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"verified", "citizen_report", "needs_review", "removed"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v


class PersonBulkCreate(BaseModel):
    people: list[PersonCreate] = Field(min_length=1, max_length=500)


class HospitalInfo(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class ServicioInfo(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class ApiKeyInfo(BaseModel):
    id: uuid.UUID
    team_name: str
    key_prefix: str

    model_config = {"from_attributes": True}


class PersonResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    document_id: str | None
    age: int | None
    hospital: HospitalInfo | None
    servicio: ServicioInfo | None
    lugar_procedencia: str | None
    relevant_info: str | None
    source_url: str | None
    status: str
    api_key: ApiKeyInfo | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PersonStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"verified", "citizen_report", "needs_review", "removed"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v


class DeleteBySourceUrl(BaseModel):
    source_url: str = Field(min_length=1, max_length=2000)


# ── Search ─────────────────────────────────────────────────────────────────────

class SearchParams(BaseModel):
    q: str | None = Field(default=None, min_length=2, max_length=100)
    name: str | None = Field(default=None, min_length=2, max_length=100)
    document_id: str | None = Field(default=None, min_length=5, max_length=12)
    hospital: str | None = Field(default=None, min_length=2, max_length=200)
    procedencia: str | None = Field(default=None, min_length=2, max_length=200)
    status: str | None = None
    page: int = Field(default=1, ge=1, le=500)
    page_size: int = Field(default=10, ge=1, le=100)

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, v: str | None) -> str | None:
        if v is not None:
            return re.sub(r"\D", "", v)
        return v


class PaginatedResponse(BaseModel):
    data: list[PersonResponse]
    pagination: dict[str, int]


class BulkUpsertResponse(BaseModel):
    upserted: int
    skipped: int
    data: list[PersonResponse]


# ── API Key schemas ────────────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    team_name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class ApiKeyCreated(BaseModel):
    id: uuid.UUID
    key: str
    key_prefix: str
    team_name: str
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyListItem(BaseModel):
    id: uuid.UUID
    key_prefix: str
    team_name: str
    description: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
