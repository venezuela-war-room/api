import hashlib
import re
import unicodedata
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import ApiKey, FoundPerson, Instalacion, Ubicacion
from app.schemas import PersonCreate, SearchParams


def _utcnow() -> datetime:
    # Assign a concrete Python value (not func.now()) so the attribute survives flush
    # without needing a DB refresh — important since merge_instalacion reads geocoded_at.
    return datetime.now(timezone.utc)


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


# Conservative facility-name canonicalization, the deterministic first line of dedup.
# Abbreviations are expanded so e.g. "Hosp." and "Hospital" align; honorifics/connectors
# are dropped. The facility-TYPE word (hospital, clinica, …) is deliberately KEPT so two
# genuinely different places ("Hospital Vargas" vs "Clínica Vargas") stay distinct.
_FACILITY_ABBREVIATIONS = {
    "hosp": "hospital",
    "hptal": "hospital",
    "gral": "general",
    "univ": "universitario",
    "ctro": "centro",
    "js": "jose",
    "dr": "",
    "dra": "",
    "sr": "",
    "sra": "",
}
_FACILITY_STOPWORDS = {"de", "del", "la", "el", "los", "las", "y"}


def _normalize_facility(nombre: str) -> str:
    s = unicodedata.normalize("NFKD", nombre)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"\([^)]*\)", " ", s)  # drop parenthetical qualifiers, e.g. "(El Llanito)"
    s = re.sub(r"[^a-z0-9 ]", " ", s)  # punctuation → space
    tokens: list[str] = []
    for tok in s.split():
        tok = _FACILITY_ABBREVIATIONS.get(tok, tok)
        if tok and tok not in _FACILITY_STOPWORDS:
            tokens.append(tok)
    result = " ".join(tokens)
    # Fall back to the basic normalization if canonicalization stripped everything.
    return result or _normalize(nombre)


# Words that name a real, geocodeable facility TYPE. A `ubicacion_actual` containing one
# is treated as a facility; otherwise it is likely free-text and routed to ubicacion.detalles.
_FACILITY_KEYWORDS = {
    "hospital", "clinica", "ambulatorio", "maternidad", "cdi", "cdm", "centro",
    "policlinica", "policlinico", "dispensario", "hospitalito", "materno", "modulo",
    "albergue", "refugio", "morgue", "ipasme", "ivss", "seguro", "sanatorio", "instituto",
}
# Tokens that signal prose/description rather than a place name ("está en el área de…").
_PROSE_MARKERS = {
    "esta", "estan", "en", "area", "areas", "se", "encuentra", "encuentran", "fue",
    "fueron", "ingreso", "ingresado", "ingresada", "trasladado", "trasladada",
    "trasladaron", "lo", "piso", "cama", "sala", "su", "para", "que", "ubicado",
    "ubicada", "reportado", "segun", "presenta", "con",
}
_MAX_NAME_TOKENS = 4  # a keyword-less real name (e.g. "Perez Carreno") is short
_MAX_FACILITY_TOKENS = 6  # a keyword + lots of prose words → it's prose mentioning a place


def _has_facility_keyword(nombre: str) -> bool:
    """True if the name contains a facility-TYPE word (hospital, albergue, …)."""
    return any(t in _FACILITY_KEYWORDS for t in _normalize_facility(nombre).split())


def _looks_like_facility(nombre: str) -> bool:
    """Heuristic: does this string name a real (geocodeable) facility, or is it free text?

    Deterministic first-pass gate at ingestion; the geocoding worker is the backstop that
    demotes anything keyword-less that fails to resolve.
    """
    tokens = _normalize_facility(nombre).split()
    if not tokens:
        return False
    has_keyword = any(t in _FACILITY_KEYWORDS for t in tokens)
    has_prose = any(t in _PROSE_MARKERS for t in tokens)
    if has_keyword:
        # A keyword buried in a long, prose-y string is description, not a name.
        return not (has_prose and len(tokens) > _MAX_FACILITY_TOKENS)
    # No keyword: only a short, prose-free string is plausibly a bare facility name.
    return not has_prose and len(tokens) <= _MAX_NAME_TOKENS


def _combine_detalles(*parts: str | None) -> str | None:
    """Join non-empty location-detail fragments into one, deduped, preserving order."""
    seen: list[str] = []
    for part in parts:
        if part and part.strip() and part.strip() not in seen:
            seen.append(part.strip())
    return " — ".join(seen) or None


def _compute_hash(full_name: str, document_id: str | None, ubicacion_actual: str | None, tipo_instalacion: str | None) -> str:
    parts = "|".join([full_name.lower(), document_id or "", ubicacion_actual or "", tipo_instalacion or ""])
    return hashlib.sha256(parts.encode()).hexdigest()


async def find_or_create_instalacion(
    db: AsyncSession,
    tipo: str,
    nombre: str,
    direccion: str | None = None,
) -> Instalacion:
    norm = _normalize_facility(nombre)
    result = await db.execute(
        select(Instalacion).where(Instalacion.tipo == tipo, Instalacion.normalized_nombre == norm)
    )
    instalacion = result.scalar_one_or_none()
    if not instalacion:
        # A client-supplied address means we never need to geocode → mark it done.
        # Otherwise leave geocoded_at NULL so the background worker picks it up.
        instalacion = Instalacion(
            tipo=tipo,
            nombre=nombre,
            normalized_nombre=norm,
            direccion=direccion,
            geocoded_at=_utcnow() if direccion else None,
        )
        db.add(instalacion)
        await db.flush()
    elif instalacion.direccion is None and direccion is not None:
        # Backfill an existing facility that was first created without an address.
        instalacion.direccion = direccion
        instalacion.geocoded_at = _utcnow()
        await db.flush()
    return instalacion


async def find_or_create_ubicacion(
    db: AsyncSession,
    instalacion_id: uuid.UUID | None,
    detalles: str | None,
) -> Ubicacion:
    norm_detalles = _normalize(detalles) if detalles else ""
    result = await db.execute(
        select(Ubicacion).where(
            Ubicacion.instalacion_id == instalacion_id,
            Ubicacion.normalized_detalles == norm_detalles,
        )
    )
    ubicacion = result.scalar_one_or_none()
    if not ubicacion:
        ubicacion = Ubicacion(
            instalacion_id=instalacion_id,
            detalles=detalles,
            normalized_detalles=norm_detalles,
        )
        db.add(ubicacion)
        await db.flush()
    return ubicacion


async def merge_instalacion(db: AsyncSession, source: Instalacion, target: Instalacion) -> Instalacion:
    """Fold ``source`` into ``target`` so a real place has a single facility row.

    Reassigns ``source``'s ubicaciones to ``target``, respecting the
    ``(instalacion_id, normalized_detalles)`` uniqueness (colliding wards are merged and
    their people repointed), copies any canonical fields ``target`` is missing, then
    deletes ``source``. Returns ``target``.
    """
    if source.id == target.id:
        return target

    target_ubis = await db.execute(select(Ubicacion).where(Ubicacion.instalacion_id == target.id))
    target_detalles = {u.normalized_detalles: u.id for u in target_ubis.scalars().all()}

    source_ubis = await db.execute(select(Ubicacion).where(Ubicacion.instalacion_id == source.id))
    # Core (not ORM) updates/deletes by id: ORM cascade handling would lazy-load
    # relationships, which isn't allowed inside the async session.
    for ubi in source_ubis.scalars().all():
        existing_id = target_detalles.get(ubi.normalized_detalles)
        if existing_id is not None:
            # Same ward already exists on the target — repoint people, drop the dup ward.
            await db.execute(
                update(FoundPerson).where(FoundPerson.ubicacion_id == ubi.id).values(ubicacion_id=existing_id)
            )
            await db.execute(delete(Ubicacion).where(Ubicacion.id == ubi.id))
        else:
            await db.execute(
                update(Ubicacion).where(Ubicacion.id == ubi.id).values(instalacion_id=target.id)
            )
            target_detalles[ubi.normalized_detalles] = ubi.id

    # Backfill canonical fields the target is missing from the source.
    if target.direccion is None and source.direccion is not None:
        target.direccion = source.direccion
        target.lat = source.lat
        target.lon = source.lon
    if target.osm_id is None and source.osm_id is not None:
        target.osm_id = source.osm_id
    if target.geocoded_at is None and source.geocoded_at is not None:
        target.geocoded_at = source.geocoded_at

    await db.flush()  # persist FK reassignments + target backfill before removing the source
    await db.execute(delete(Instalacion).where(Instalacion.id == source.id))
    db.expunge(source)
    return target


async def demote_instalacion_to_detalle(db: AsyncSession, inst: Instalacion) -> None:
    """Turn a facility row back into plain location detail(s) with no facility.

    Used when a string that slipped past the ingestion gate turns out not to be a real
    place (the geocoder finds no match). Each of the facility's ubicaciones keeps its
    people but loses the facility link; the facility name is folded into `detalles` so the
    information isn't lost. Colliding NULL-facility wards are merged. Core SQL throughout
    (ORM cascade would lazy-load in the async session).
    """
    # Existing NULL-facility ubicaciones we might collide with after demotion.
    null_ubis = await db.execute(
        select(Ubicacion.id, Ubicacion.normalized_detalles).where(Ubicacion.instalacion_id.is_(None))
    )
    by_detalles = {norm: uid for uid, norm in null_ubis.all()}

    source_ubis = await db.execute(select(Ubicacion).where(Ubicacion.instalacion_id == inst.id))
    for ubi in source_ubis.scalars().all():
        new_detalles = _combine_detalles(inst.nombre, ubi.detalles)
        new_norm = _normalize(new_detalles) if new_detalles else ""
        existing_id = by_detalles.get(new_norm)
        if existing_id is not None and existing_id != ubi.id:
            # A NULL-facility ward with the same text already exists — fold into it.
            await db.execute(
                update(FoundPerson).where(FoundPerson.ubicacion_id == ubi.id).values(ubicacion_id=existing_id)
            )
            await db.execute(delete(Ubicacion).where(Ubicacion.id == ubi.id))
        else:
            await db.execute(
                update(Ubicacion)
                .where(Ubicacion.id == ubi.id)
                .values(instalacion_id=None, detalles=new_detalles, normalized_detalles=new_norm)
            )
            by_detalles[new_norm] = ubi.id

    await db.flush()
    await db.execute(delete(Instalacion).where(Instalacion.id == inst.id))
    db.expunge(inst)


def _person_load_options():
    return [
        selectinload(FoundPerson.ubicacion).selectinload(Ubicacion.instalacion),
        selectinload(FoundPerson.api_key),
    ]


async def upsert_person(
    db: AsyncSession,
    payload: PersonCreate,
    api_key_id: uuid.UUID | None = None,
) -> tuple[FoundPerson, bool]:
    ubicacion_id: uuid.UUID | None = None

    if payload.ubicacion_actual and _looks_like_facility(payload.ubicacion_actual):
        tipo = payload.tipo_instalacion or "unknown"
        # Store any client-supplied address; coordinates are filled later by the
        # background geocoding worker (app/geocoding_worker.py).
        instalacion = await find_or_create_instalacion(
            db, tipo, payload.ubicacion_actual, direccion=payload.direccion
        )
        ubicacion = await find_or_create_ubicacion(db, instalacion.id, payload.ubicacion_detalles)
        ubicacion_id = ubicacion.id
    else:
        # ubicacion_actual is free-text (not a real facility) — keep it as a location
        # detail with no facility, alongside any explicit detalles. Never geocoded.
        detalles = _combine_detalles(payload.ubicacion_actual, payload.ubicacion_detalles)
        if detalles:
            ubicacion = await find_or_create_ubicacion(db, None, detalles)
            ubicacion_id = ubicacion.id

    source_hash = payload.source_hash or _compute_hash(
        payload.full_name, payload.document_id, payload.ubicacion_actual, payload.tipo_instalacion
    )

    stmt = (
        insert(FoundPerson)
        .values(
            full_name=payload.full_name,
            document_id=payload.document_id,
            age=payload.age,
            ubicacion_id=ubicacion_id,
            lugar_procedencia=payload.lugar_procedencia,
            relevant_info=payload.relevant_info,
            fallecido=payload.fallecido,
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
                "ubicacion_id": ubicacion_id,
                "lugar_procedencia": payload.lugar_procedencia,
                "relevant_info": payload.relevant_info,
                "fallecido": payload.fallecido,
                "source_url": payload.source_url,
                "status": payload.status,
                "raw": payload.raw,
                "updated_at": func.now(),
            },
        )
        # xmax = 0 on a freshly inserted row; non-zero when ON CONFLICT updated it.
        .returning(FoundPerson.id, literal_column("(xmax = 0)").label("inserted"))
    )

    result = await db.execute(stmt)
    row = result.fetchone()
    person = await _load_person(db, row[0])
    return person, bool(row[1])


async def _load_person(db: AsyncSession, person_id: uuid.UUID) -> FoundPerson:
    result = await db.execute(
        select(FoundPerson)
        .where(FoundPerson.id == person_id)
        .options(*_person_load_options())
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def search_people(db: AsyncSession, params: SearchParams) -> tuple[list[FoundPerson], int]:
    base = (
        select(FoundPerson)
        .options(*_person_load_options())
        .where(FoundPerson.status != "removed")
    )

    if params.document_id:
        base = base.where(FoundPerson.document_id == params.document_id)

    if params.name:
        base = base.where(func.unaccent(FoundPerson.full_name).ilike(f"%{params.name}%"))

    if params.q:
        pattern = f"%{params.q}%"
        base = base.where(
            func.unaccent(FoundPerson.full_name).ilike(pattern)
            | func.unaccent(FoundPerson.lugar_procedencia).ilike(pattern)
            | func.unaccent(FoundPerson.relevant_info).ilike(pattern)
        )

    if params.ubicacion or params.tipo_instalacion:
        base = base.join(FoundPerson.ubicacion).join(Ubicacion.instalacion)
        if params.ubicacion:
            base = base.where(func.unaccent(Instalacion.nombre).ilike(f"%{params.ubicacion}%"))
        if params.tipo_instalacion:
            base = base.where(Instalacion.tipo == params.tipo_instalacion)

    if params.procedencia:
        base = base.where(func.unaccent(FoundPerson.lugar_procedencia).ilike(f"%{params.procedencia}%"))

    if params.fallecido is not None:
        base = base.where(FoundPerson.fallecido == params.fallecido)

    if params.status:
        base = base.where(FoundPerson.status == params.status)

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar_one()

    offset = (params.page - 1) * params.page_size
    rows = await db.execute(base.order_by(FoundPerson.updated_at.desc()).offset(offset).limit(params.page_size))
    return list(rows.scalars().all()), total


async def get_person_by_id(db: AsyncSession, person_id: uuid.UUID) -> FoundPerson | None:
    result = await db.execute(
        select(FoundPerson).where(FoundPerson.id == person_id).options(*_person_load_options())
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
