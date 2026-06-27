import pytest
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
        if matched.nombre in names:
            out[matched.nombre] = GeocodeOutcome(GeocodeResult("Calle 1, Caracas", 10.5, -66.9), True)
        if no_match.nombre in names:
            out[no_match.nombre] = geocoding.NO_MATCH
        if transient.nombre in names:
            out[transient.nombre] = geocoding.TRANSIENT
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
