import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

TIPOS_INSTALACION = {"hospital", "albergue", "morgue", "punto_concentracion", "centro_medico", "unknown"}


class Instalacion(Base):
    __tablename__ = "instalaciones"
    __table_args__ = (UniqueConstraint("tipo", "normalized_nombre", name="uq_instalacion_tipo_nombre"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    tipo: Mapped[str] = mapped_column(String, nullable=False)
    nombre: Mapped[str] = mapped_column(String, nullable=False)
    normalized_nombre: Mapped[str] = mapped_column(String, nullable=False)
    direccion: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    ubicaciones: Mapped[list["Ubicacion"]] = relationship(back_populates="instalacion")


class Ubicacion(Base):
    __tablename__ = "ubicaciones"
    __table_args__ = (
        UniqueConstraint(
            "instalacion_id",
            "normalized_detalles",
            name="uq_ubicacion_instalacion_detalles",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    instalacion_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("instalaciones.id"), nullable=True)
    detalles: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_detalles: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    instalacion: Mapped["Instalacion | None"] = relationship(back_populates="ubicaciones")
    people: Mapped[list["FoundPerson"]] = relationship(back_populates="ubicacion")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    key_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    team_name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    people: Mapped[list["FoundPerson"]] = relationship(back_populates="api_key")


class FoundPerson(Base):
    __tablename__ = "found_people"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    document_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ubicacion_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ubicaciones.id"), nullable=True, index=True)
    lugar_procedencia: Mapped[str | None] = mapped_column(String, nullable=True)
    relevant_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallecido: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    source_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String, default="verified", nullable=False, index=True)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("api_keys.id"), nullable=True, index=True)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    ubicacion: Mapped["Ubicacion | None"] = relationship(back_populates="people")
    api_key: Mapped["ApiKey | None"] = relationship(back_populates="people")
