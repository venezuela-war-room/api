import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import geocoding, geocoding_worker
from app.config import settings
from app.geocoding import GeocodeOutcome, GeocodeResult
from app.models import Instalacion


async def _seed(db: AsyncSession, nombre: str) -> Instalacion:
    inst = Instalacion(tipo="hospital", nombre=nombre, normalized_nombre=nombre.lower())
    db.add(inst)
    await db.flush()
    return inst


@pytest.mark.asyncio
async def test_process_pending_batch_applies_outcomes(db: AsyncSession, monkeypatch):
    # Large batch so all pending rows are claimed in one pass; unique names avoid
    # collisions with other tests.
    monkeypatch.setattr(settings, "geocoding_batch_size", 10_000)

    matched = await _seed(db, "Worker Matched Hosp")
    no_match = await _seed(db, "Worker NoMatch Hosp")
    transient = await _seed(db, "Worker Transient Hosp")
    await db.commit()

    async def fake_geocode_batch(names):
        names = set(names)
        out: dict[str, GeocodeOutcome] = {}
        if matched.normalized_nombre in names:
            out[matched.normalized_nombre] = GeocodeOutcome(GeocodeResult("Calle 1, Caracas", 10.5, -66.9), True)
        if no_match.normalized_nombre in names:
            out[no_match.normalized_nombre] = geocoding.NO_MATCH
        if transient.normalized_nombre in names:
            out[transient.normalized_nombre] = geocoding.TRANSIENT
        # Any other pending rows from other tests get no outcome → left pending.
        return out

    monkeypatch.setattr(geocoding_worker, "geocode_batch", fake_geocode_batch)

    processed = await geocoding_worker.process_pending_batch(db)
    assert processed >= 2  # matched + no_match counted; transient is not

    for inst in (matched, no_match, transient):
        await db.refresh(inst)

    # Matched: address + coords + stamped done.
    assert matched.direccion == "Calle 1, Caracas"
    assert matched.lat == 10.5
    assert matched.lon == -66.9
    assert matched.geocoded_at is not None

    # No match: stamped done so we stop retrying, but no address.
    assert no_match.direccion is None
    assert no_match.geocoded_at is not None

    # Transient: left pending for a future retry.
    assert transient.direccion is None
    assert transient.geocoded_at is None


@pytest.mark.asyncio
async def test_claim_pending_skips_already_geocoded(db: AsyncSession):
    done = Instalacion(
        tipo="hospital",
        nombre="Worker Already Done Hosp",
        normalized_nombre="worker already done hosp",
        direccion="Existing address",
    )
    # Simulate a row that was already processed.
    from sqlalchemy.sql import func

    done.geocoded_at = func.now()
    db.add(done)
    await db.commit()
    await db.refresh(done)

    claimed = await geocoding_worker.claim_pending(db, limit=10_000)
    assert done.id not in {c.id for c in claimed}


@pytest.mark.asyncio
async def test_worker_merges_facilities_with_same_osm_id(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "geocoding_batch_size", 10_000)
    a = await _seed(db, "Hospital Domingo Luciani WK")
    b = await _seed(db, "Hosp Domingo Luciani WK")
    await db.commit()
    osm = "way/700700700"

    async def fake_geocode_batch(names):
        names = set(names)
        out = {}
        for n in (a.normalized_nombre, b.normalized_nombre):
            if n in names:
                out[n] = GeocodeOutcome(GeocodeResult("Addr", 10.0, -66.0, osm_id=osm), True)
        return out

    monkeypatch.setattr(geocoding_worker, "geocode_batch", fake_geocode_batch)

    await geocoding_worker.process_pending_batch(db)

    # The two name variants collapsed into one facility keyed on the OSM place.
    same_place = (await db.execute(select(Instalacion).where(Instalacion.osm_id == osm))).scalars().all()
    assert len(same_place) == 1
    remaining = (
        await db.execute(select(Instalacion).where(Instalacion.id.in_([a.id, b.id])))
    ).scalars().all()
    assert len(remaining) == 1  # the other row was merged away


@pytest.mark.asyncio
async def test_worker_keeps_distinct_osm_ids_separate(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "geocoding_batch_size", 10_000)
    a = await _seed(db, "Distinct OSM A WK")
    b = await _seed(db, "Distinct OSM B WK")
    await db.commit()

    async def fake_geocode_batch(names):
        names = set(names)
        out = {}
        if a.normalized_nombre in names:
            out[a.normalized_nombre] = GeocodeOutcome(GeocodeResult("A", 1.0, 2.0, osm_id="way/111"), True)
        if b.normalized_nombre in names:
            out[b.normalized_nombre] = GeocodeOutcome(GeocodeResult("B", 3.0, 4.0, osm_id="way/222"), True)
        return out

    monkeypatch.setattr(geocoding_worker, "geocode_batch", fake_geocode_batch)

    await geocoding_worker.process_pending_batch(db)

    remaining = (
        await db.execute(select(Instalacion).where(Instalacion.id.in_([a.id, b.id])))
    ).scalars().all()
    assert len(remaining) == 2  # different places stay separate
