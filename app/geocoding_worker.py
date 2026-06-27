"""Background worker that fills facility addresses from OpenStreetMap.

Geocoding is kept off the request path: ingestion stores facilities with
``geocoded_at IS NULL`` (unless the client supplied an address), and this worker drains
that queue continuously. ``claim_pending`` uses ``FOR UPDATE SKIP LOCKED`` so multiple
processes/replicas never geocode the same row.

Outcome handling per facility:
- matched      → write direccion/lat/lon, stamp ``geocoded_at`` (done)
- no match     → stamp ``geocoded_at`` only (done — don't keep re-querying a dead end)
- transient    → leave ``geocoded_at`` NULL (retried next cycle)
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.config import settings
from app.database import AsyncSessionLocal
from app.geocoding import geocode_batch
from app.models import Instalacion

logger = logging.getLogger(__name__)


async def claim_pending(db: AsyncSession, limit: int) -> list[Instalacion]:
    """Lock and return up to ``limit`` facilities still needing geocoding."""
    result = await db.execute(
        select(Instalacion)
        .where(Instalacion.geocoded_at.is_(None))
        .order_by(Instalacion.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def process_pending_batch(db: AsyncSession) -> int:
    """Claim, geocode, and update one batch of pending facilities. Returns count processed.

    Shared by the in-app worker loop and ``scripts/backfill_addresses.py``.
    """
    instalaciones = await claim_pending(db, settings.geocoding_batch_size)
    if not instalaciones:
        return 0

    logger.info("Geocoding batch: claimed %d pending facilit(ies).", len(instalaciones))

    # Geocode the canonical (normalized) name, not the raw one: Nominatim fails on
    # abbreviations like "Hosp. Domingo Luciani" but resolves "hospital domingo luciani",
    # which also lets variants converge on the same osm_id.
    outcomes = await geocode_batch(i.normalized_nombre for i in instalaciones)

    geocoded = merged = no_match = demoted = skipped = 0
    now = crud._utcnow()
    # Canonical facility per OSM place resolved during this batch (catches intra-batch dups
    # before they hit the partial-unique index on osm_id).
    seen_osm: dict[str, Instalacion] = {}
    for inst in instalaciones:
        outcome = outcomes.get(inst.normalized_nombre)
        if outcome is None or not outcome.completed:
            # Geocoding disabled or a transient failure — leave pending for a retry.
            skipped += 1
            logger.debug("Facility %s %r: no result (transient/disabled); left pending.", inst.id, inst.nombre)
            continue
        result = outcome.result

        if result and result.osm_id:
            canonical = seen_osm.get(result.osm_id)
            if canonical is None:
                existing = await db.execute(
                    select(Instalacion)
                    .where(Instalacion.osm_id == result.osm_id)
                    .with_for_update()
                )
                canonical = existing.scalar_one_or_none()
            if canonical is not None and canonical.id != inst.id:
                # Same real place already has a facility row — fold this one into it.
                logger.info(
                    "Merged facility %s %r into %s %r (osm_id=%s).",
                    inst.id, inst.nombre, canonical.id, canonical.nombre, result.osm_id,
                )
                await crud.merge_instalacion(db, inst, canonical)
                seen_osm[result.osm_id] = canonical
                merged += 1
                continue
            inst.osm_id = result.osm_id
            seen_osm[result.osm_id] = inst

        if result:
            inst.direccion = result.direccion
            inst.lat = result.lat
            inst.lon = result.lon
            inst.geocoded_at = now
            geocoded += 1
            logger.info(
                "Geocoded facility %s %r -> osm_id=%s, direccion=%r.",
                inst.id, inst.nombre, result.osm_id, result.direccion,
            )
        elif crud._has_facility_keyword(inst.nombre):
            # A named facility (e.g. "Hospital …") OSM just doesn't have — keep it as an
            # unconfirmed facility (osm_id stays NULL); don't destroy a real place.
            inst.geocoded_at = now
            no_match += 1
            logger.info("Facility %s %r: no OSM match but named facility; kept unconfirmed.", inst.id, inst.nombre)
        else:
            # Keyword-less and unresolvable — it slipped past the ingest gate and is almost
            # certainly free text. Demote it back to a plain location detail.
            logger.info("Facility %s %r: no OSM match and not a named facility; demoting to detalle.", inst.id, inst.nombre)
            await crud.demote_instalacion_to_detalle(db, inst)
            demoted += 1

    await db.commit()
    logger.info(
        "Geocoding batch done: %d geocoded, %d merged, %d no-match, %d demoted, %d left pending (of %d claimed).",
        geocoded, merged, no_match, demoted, skipped, len(instalaciones),
    )
    return geocoded + merged + no_match + demoted


async def run_worker() -> None:
    """Recurring loop: drain the geocoding queue, then idle. Never dies on errors."""
    if not (settings.geocoding_worker_enabled and settings.geocoding_enabled):
        logger.info("Geocoding worker disabled; not starting.")
        return

    logger.info("Geocoding worker started.")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                processed = await process_pending_batch(db)
            if processed == 0:
                await asyncio.sleep(settings.geocoding_worker_interval)
        except asyncio.CancelledError:
            logger.info("Geocoding worker stopped.")
            raise
        except Exception:  # keep the loop alive across unexpected errors
            logger.exception("Geocoding worker cycle failed; retrying after interval.")
            await asyncio.sleep(settings.geocoding_worker_interval)
