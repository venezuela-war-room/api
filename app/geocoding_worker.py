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
from sqlalchemy.sql import func

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

    outcomes = await geocode_batch(i.nombre for i in instalaciones)

    processed = 0
    now = func.now()
    for inst in instalaciones:
        outcome = outcomes.get(inst.nombre)
        if outcome is None or not outcome.completed:
            # Geocoding disabled or a transient failure — leave pending for a retry.
            continue
        if outcome.result:
            inst.direccion = outcome.result.direccion
            inst.lat = outcome.result.lat
            inst.lon = outcome.result.lon
        inst.geocoded_at = now
        processed += 1

    await db.commit()
    return processed


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
