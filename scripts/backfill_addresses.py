"""Drain the facility geocoding queue from the command line.

Geocoding normally runs as an in-app background worker (app/geocoding_worker.py). This
script runs the same `process_pending_batch` logic on demand — useful for backfilling
without starting the web app, or in a deployment where the worker is disabled
(`GEOCODING_WORKER_ENABLED=false`).

Usage:
    uv run python scripts/backfill_addresses.py             # drain all pending facilities
    uv run python scripts/backfill_addresses.py --limit 50  # stop after ~50 processed
    uv run python scripts/backfill_addresses.py --dry-run   # count pending, write nothing

⚠️ Respects app.config geocoding settings. Against the PUBLIC Nominatim endpoint keep
`GEOCODING_CONCURRENCY=1` to comply with its usage policy; raise it only when pointing at
a self-hosted/commercial instance.
"""

import argparse
import asyncio

from sqlalchemy import func, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.geocoding_worker import process_pending_batch
from app.models import Instalacion


async def _count_pending() -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(func.count()).select_from(Instalacion).where(Instalacion.geocoded_at.is_(None))
        )
        return result.scalar_one()


async def backfill(limit: int | None, dry_run: bool) -> None:
    if not settings.geocoding_enabled:
        print("Geocoding is disabled (GEOCODING_ENABLED=false). Nothing to do.")
        return

    pending = await _count_pending()
    print(f"{pending} facilities pending geocoding.")
    if dry_run:
        print("Dry run: no changes written.")
        return
    if pending == 0:
        return

    total = 0
    while True:
        async with AsyncSessionLocal() as db:
            processed = await process_pending_batch(db)
        if processed == 0:
            break
        total += processed
        print(f"  processed {total}...")
        if limit is not None and total >= limit:
            break

    print(f"Done: processed {total} facilities.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill instalacion addresses via OpenStreetMap.")
    parser.add_argument("--limit", type=int, default=None, help="Approx. max facilities to process.")
    parser.add_argument("--dry-run", action="store_true", help="Count pending without writing.")
    args = parser.parse_args()
    asyncio.run(backfill(args.limit, args.dry_run))


if __name__ == "__main__":
    main()
