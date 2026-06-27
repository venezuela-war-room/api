"""Collapse duplicate facilities already in the database.

Two facilities are the same real place when their names canonicalize to the same key
(`crud._normalize_facility`). This script regroups existing `instalaciones` under the
current normalization and merges duplicates within each `tipo`, keeping the oldest row as
canonical. Use it once after deploying a normalization change (the OSM-id layer dedups the
rest automatically as the worker geocodes).

Usage:
    uv run python scripts/dedup_facilities.py            # dry run (default) — preview only
    uv run python scripts/dedup_facilities.py --apply    # perform the merges

The merge itself is `crud.merge_instalacion` (reassigns wards/people, deletes the dup).
"""

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make `app` importable

from sqlalchemy import select  # noqa: E402

from app.crud import _normalize_facility, merge_instalacion  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models import Instalacion  # noqa: E402


async def dedup(apply: bool) -> None:
    async with AsyncSessionLocal() as db:
        rows = list(
            (await db.execute(select(Instalacion).order_by(Instalacion.created_at))).scalars().all()
        )

        groups: dict[tuple[str, str], list[Instalacion]] = defaultdict(list)
        for inst in rows:
            groups[(inst.tipo, _normalize_facility(inst.nombre))].append(inst)

        merged = 0
        survivors: list[tuple[Instalacion, str]] = []
        for (tipo, new_norm), members in groups.items():
            canonical = members[0]  # oldest (rows ordered by created_at)
            for dup in members[1:]:
                print(f"  merge  {dup.nombre!r}  ->  {canonical.nombre!r}   [{tipo} :: {new_norm}]")
                merged += 1
                if apply:
                    await merge_instalacion(db, dup, canonical)
            survivors.append((canonical, new_norm))

        if not apply:
            print(f"\nDry run: {merged} facilities would be merged. Re-run with --apply to perform.")
            return

        # Recanonicalize stored normalized_nombre in two phases so an intermediate UPDATE
        # never transiently collides with another row on uq_instalacion_tipo_nombre.
        changing = [(inst, n) for inst, n in survivors if inst.normalized_nombre != n]
        for inst, _ in changing:
            inst.normalized_nombre = f"__dedup_migrating__{inst.id}"
        await db.flush()
        for inst, new_norm in changing:
            inst.normalized_nombre = new_norm
        await db.flush()
        await db.commit()
        print(f"\nApplied: merged {merged} facilities; recanonicalized {len(changing)} names.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge duplicate facilities by canonical name.")
    parser.add_argument("--apply", action="store_true", help="Perform merges (default is dry run).")
    args = parser.parse_args()
    asyncio.run(dedup(args.apply))


if __name__ == "__main__":
    main()
