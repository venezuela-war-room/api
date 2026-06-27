import re
import unicodedata
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator, model_validator

TIPOS_INSTALACION = {"hospital", "albergue", "morgue", "punto_concentracion", "centro_medico", "unknown"}


def _clean_str(v: str) -> str:
    v = unicodedata.normalize("NFKC", v)
    v = re.sub(r"[\x00-\x1f\x7f]", "", v)
    return " ".join(v.split())


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
    ubicacion_actual: str | None = Field(default=None, min_length=2, max_length=300)
    tipo_instalacion: str | None = Field(default=None)
    direccion: str | None = Field(
        default=None,
        min_length=2,
        max_length=500,
        description="Facility street address. If omitted, it is geocoded from the facility name via OpenStreetMap.",
    )
    ubicacion_detalles: str | None = Field(default=None, min_length=1, max_length=500)
    lugar_procedencia: str | None = Field(default=None, min_length=1, max_length=300)
    relevant_info: str | None = Field(default=None, max_length=5000)
    fallecido: bool = False
    source_url: str | None = Field(default=None, max_length=2000)
    source_hash: str | None = Field(default=None, min_length=8, max_length=128)
    status: str = Field(default="verified")
    raw: dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "full_name": "Álvarez Maikeli",
                    "document_id": "30045442",
                    "age": 34,
                    "ubicacion_actual": "Hospital José Gregorio Hernández",
                    "tipo_instalacion": "hospital",
                    "direccion": "Av. José Ángel Lamas, San Juan, Caracas",
                    "ubicacion_detalles": "Lista de pacientes, piso 3",
                    "lugar_procedencia": "La Guaira",
                    "relevant_info": "Politraumatismo, estable",
                    "fallecido": False,
                    "source_url": "https://example.org/listado-pacientes",
                    "source_hash": "a1b2c3d4e5f6",
                    "status": "verified",
                }
            ]
        }
    }

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, v: str | None) -> str | None:
        if v is not None:
            digits = re.sub(r"\D", "", v)
            if not digits:
                raise ValueError("document_id must contain digits")
            return digits
        return v

    @field_validator("tipo_instalacion")
    @classmethod
    def validate_tipo(cls, v: str | None) -> str | None:
        if v is not None and v not in TIPOS_INSTALACION:
            raise ValueError(f"tipo_instalacion must be one of {sorted(TIPOS_INSTALACION)}")
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

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "people": [
                        {
                            "full_name": "Álvarez Maikeli",
                            "document_id": "30045442",
                            "ubicacion_actual": "Hospital José Gregorio Hernández",
                            "tipo_instalacion": "hospital",
                            "source_hash": "a1b2c3d4e5f6",
                        },
                        {
                            "full_name": "Aguero Johanna",
                            "document_id": "37454987",
                            "ubicacion_actual": "Albergue Catia",
                            "tipo_instalacion": "albergue",
                            "source_hash": "f6e5d4c3b2a1",
                        },
                    ]
                }
            ]
        }
    }


# ── Response schemas ───────────────────────────────────────────────────────────

class InstalacionInfo(BaseModel):
    id: uuid.UUID
    tipo: str
    nombre: str
    direccion: str | None
    lat: float | None
    lon: float | None

    model_config = {"from_attributes": True}


class UbicacionInfo(BaseModel):
    id: uuid.UUID
    instalacion: InstalacionInfo | None
    detalles: str | None

    model_config = {"from_attributes": True}


class PersonResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    document_id: str | None
    age: int | None
    ubicacion: UbicacionInfo | None
    lugar_procedencia: str | None
    relevant_info: str | None
    fallecido: bool
    source_url: str | None
    status: str
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
    document_id: str | None = Field(default=None, min_length=1, max_length=12)
    ubicacion: str | None = Field(default=None, min_length=2, max_length=200)
    tipo_instalacion: str | None = None
    procedencia: str | None = Field(default=None, min_length=2, max_length=200)
    fallecido: bool | None = None
    status: str | None = None
    page: int = Field(default=1, ge=1, le=500)
    page_size: int = Field(default=10, ge=1, le=100)

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, v: str | None) -> str | None:
        if v is not None:
            return re.sub(r"\D", "", v) or None
        return v

    @field_validator("tipo_instalacion")
    @classmethod
    def validate_tipo(cls, v: str | None) -> str | None:
        if v is not None and v not in TIPOS_INSTALACION:
            raise ValueError(f"tipo_instalacion must be one of {sorted(TIPOS_INSTALACION)}")
        return v


class PaginatedResponse(BaseModel):
    data: list[PersonResponse]
    pagination: dict[str, int]


class BulkUpsertResponse(BaseModel):
    created: int
    updated: int
    data: list[PersonResponse]


# ── API Key schemas ────────────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    team_name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"team_name": "equipo-la-guaira", "description": "Voluntarios zona costera"}
            ]
        }
    }


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
