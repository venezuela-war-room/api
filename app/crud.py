import hashlib
import re
import unicodedata
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import ApiKey, FoundPerson, Hospital, Servicio
from app.schemas import PersonCreate, SearchParams


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def _compute_hash(full_name: str, document_id: str | None, hospital: str | None) -> str:
    parts = "|".join([full_name.lower(), document_id or "", hospital or ""])
    return hashlib.sha256(parts.encode()).hexdigest()


async def find_or_create_hospital(db: AsyncSession, name: str) -> Hospital:
    norm = _normalize(name)
    result = await db.execute(select(Hospital).where(Hospital.normalized_name == norm))
    hospital = result.scalar_one_or_none()
    if not hospital:
        hospital = Hospital(name=name, normalized_name=norm)
        db.add(hospital)
        await db.flush()
    return hospital


async def find_or_create_servicio(db: AsyncSession, hospital_id: uuid.UUID, name: str) -> Servicio:
    norm = _normalize(name)
    result = await db.execute(
        select(Servicio).where(Servicio.hospital_id == hospital_id, Servicio.normalized_name == norm)
    )
    servicio = result.scalar_one_or_none()
    if not servicio:
        servicio = Servicio(hospital_id=hospital_id, name=name, normalized_name=norm)
        db.add(servicio)
        await db.flush()
    return servicio


async def upsert_person(
    db: AsyncSession,
    payload: PersonCreate,
    api_key_id: uuid.UUID | None = None,
) -> tuple[FoundPerson, bool]:
    hospital_id: uuid.UUID | None = None
    servicio_id: uuid.UUID | None = None

    if payload.hospital:
        h = await find_or_create_hospital(db, payload.hospital)
        hospital_id = h.id
        if payload.servicio:
            s = await find_or_create_servicio(db, hospital_id, payload.servicio)
            servicio_id = s.id

    source_hash = payload.source_hash or _compute_hash(
        payload.full_name, payload.document_id, payload.hospital
    )

    stmt = (
        insert(FoundPerson)
        .values(
            full_name=payload.full_name,
            document_id=payload.document_id,
            age=payload.age,
            hospital_id=hospital_id,
            servicio_id=servicio_id,
            lugar_procedencia=payload.lugar_procedencia,
            relevant_info=payload.relevant_info,
            source_url=payload.source_url,
            source_hash=source_hash,
            status=payload.status,
            api_key_id=api_key_id,
            raw=payload.raw,
        )
        .on_conflict_do_update(
            index_elements=["source_hash"],
            set_={
                "full_name": payload.full_name,
                "document_id": payload.document_id,
                "age": payload.age,
                "hospital_id": hospital_id,
                "servicio_id": servicio_id,
                "lugar_procedencia": payload.lugar_procedencia,
                "relevant_info": payload.relevant_info,
                "source_url": payload.source_url,
                "status": payload.status,
                "raw": payload.raw,
                "updated_at": func.now(),
            },
        )
        .returning(FoundPerson.id, FoundPerson.source_hash)
    )

    result = await db.execute(stmt)
    row = result.fetchone()
    person = await _load_person(db, row[0])
    return person, True


async def _load_person(db: AsyncSession, person_id: uuid.UUID) -> FoundPerson:
    result = await db.execute(
        select(FoundPerson)
        .where(FoundPerson.id == person_id)
        .options(
            selectinload(FoundPerson.hospital),
            selectinload(FoundPerson.servicio),
            selectinload(FoundPerson.api_key),
        )
        # upsert_person mutates the row via a Core ON CONFLICT DO UPDATE, which the
        # ORM identity map can't see; force a refresh so we return post-upsert state.
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def search_people(db: AsyncSession, params: SearchParams) -> tuple[list[FoundPerson], int]:
    base = (
        select(FoundPerson)
        .options(
            selectinload(FoundPerson.hospital),
            selectinload(FoundPerson.servicio),
            selectinload(FoundPerson.api_key),
        )
        .where(FoundPerson.status != "removed")
    )

    if params.document_id:
        base = base.where(FoundPerson.document_id == params.document_id)

    if params.name:
        base = base.where(
            func.unaccent(FoundPerson.full_name).ilike(f"%{params.name}%")
        )

    if params.q:
        pattern = f"%{params.q}%"
        base = base.where(
            func.unaccent(FoundPerson.full_name).ilike(pattern)
            | func.unaccent(FoundPerson.lugar_procedencia).ilike(pattern)
            | func.unaccent(FoundPerson.relevant_info).ilike(pattern)
        )

    if params.hospital:
        base = base.join(FoundPerson.hospital).where(
            func.unaccent(Hospital.name).ilike(f"%{params.hospital}%")
        )

    if params.procedencia:
        base = base.where(
            func.unaccent(FoundPerson.lugar_procedencia).ilike(f"%{params.procedencia}%")
        )

    if params.status:
        base = base.where(FoundPerson.status == params.status)

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar_one()

    offset = (params.page - 1) * params.page_size
    rows = await db.execute(base.order_by(FoundPerson.updated_at.desc()).offset(offset).limit(params.page_size))
    return list(rows.scalars().all()), total


async def get_person_by_id(db: AsyncSession, person_id: uuid.UUID) -> FoundPerson | None:
    result = await db.execute(
        select(FoundPerson)
        .where(FoundPerson.id == person_id)
        .options(
            selectinload(FoundPerson.hospital),
            selectinload(FoundPerson.servicio),
            selectinload(FoundPerson.api_key),
        )
    )
    return result.scalar_one_or_none()


async def update_person_status(db: AsyncSession, person_id: uuid.UUID, new_status: str) -> FoundPerson | None:
    await db.execute(
        update(FoundPerson).where(FoundPerson.id == person_id).values(status=new_status, updated_at=func.now())
    )
    await db.flush()
    return await get_person_by_id(db, person_id)


async def soft_delete_by_source_url(db: AsyncSession, source_url: str) -> int:
    result = await db.execute(
        update(FoundPerson)
        .where(FoundPerson.source_url == source_url)
        .values(status="removed", updated_at=func.now())
        .returning(FoundPerson.id)
    )
    return len(result.fetchall())


# ── API Key CRUD ───────────────────────────────────────────────────────────────

def _generate_api_key() -> tuple[str, str, str]:
    raw = "tvwr_" + uuid.uuid4().hex + uuid.uuid4().hex
    prefix = raw[:12]
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, prefix, key_hash


async def create_api_key(db: AsyncSession, team_name: str, description: str | None) -> tuple[ApiKey, str]:
    raw, prefix, key_hash = _generate_api_key()
    api_key = ApiKey(key_prefix=prefix, key_hash=key_hash, team_name=team_name, description=description)
    db.add(api_key)
    await db.flush()
    return api_key, raw


async def list_api_keys(db: AsyncSession) -> list[ApiKey]:
    result = await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    return list(result.scalars().all())


async def revoke_api_key(db: AsyncSession, key_id: uuid.UUID) -> bool:
    result = await db.execute(
        update(ApiKey).where(ApiKey.id == key_id).values(is_active=False).returning(ApiKey.id)
    )
    return result.fetchone() is not None
