"""Seed the database with a small set of test data.

Idempotent: every row is inserted with ON CONFLICT (id) DO NOTHING, so running
this repeatedly is safe. Point DATABASE_URL at the target database first, e.g.
the docker compose Postgres:

    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/terremoto \
        uv run python scripts/seed_test_data.py

(The scheme is normalized to asyncpg automatically by app.config.)

Pass --reset to delete the seeded rows (by their known ids) before re-inserting,
for a clean wipe-and-reseed during testing.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from app.database import AsyncSessionLocal
from app.models import ApiKey, FoundPerson, Instalacion, Ubicacion

# An api_key is required by the found_people FK. None was provided in the source
# dump, so seed a placeholder with the referenced id. key_hash is a throwaway —
# it does not match any real key, it only satisfies the NOT NULL / unique columns.
API_KEYS = [
    {
        "id": "7c06fee1-a900-488e-9257-c22bf3056520",
        "key_prefix": "seed_testkey",
        "key_hash": "seed-placeholder-hash-not-a-real-key",
        "team_name": "Seed Test Team",
        "description": "Placeholder key for seeded test data",
        "is_active": True,
    },
]

INSTALACIONES = [
    {
        "id": "1ee1a816-a833-42f6-b2f3-1f6c73c6dffe",
        "tipo": "hospital",
        "nombre": "Hospital Universitario de Caracas",
        "normalized_nombre": "hospital universitario de caracas",
    },
    {
        "id": "0c35c9b0-793e-44c0-95f0-01d02a4402e1",
        "tipo": "hospital",
        "nombre": "Cruz Roja",
        "normalized_nombre": "cruz roja",
    },
    {
        "id": "1a00440b-a32c-4dc9-bcf8-83fb0bcd178e",
        "tipo": "hospital",
        "nombre": "Periférico de Catia",
        "normalized_nombre": "periferico de catia",
    },
    {
        "id": "9181e094-a8e1-4939-8abf-c194419bea94",
        "tipo": "hospital",
        "nombre": "Hospital Domingo Luciani",
        "normalized_nombre": "hospital domingo luciani",
    },
    {
        "id": "c156c5d2-e593-409a-97c8-b1c872ebb5a6",
        "tipo": "hospital",
        "nombre": "Hospital Pérez Carreño",
        "normalized_nombre": "hospital perez carreno",
    },
]

UBICACIONES = [
    {"id": "cbb718f8-4d07-4a43-ac03-6860fd668357", "instalacion_id": "1ee1a816-a833-42f6-b2f3-1f6c73c6dffe", "detalles": None, "normalized_detalles": ""},
    {"id": "f8b0d5fc-3079-4c52-b1f4-e7f8b900c753", "instalacion_id": "0c35c9b0-793e-44c0-95f0-01d02a4402e1", "detalles": None, "normalized_detalles": ""},
    {"id": "b736e277-30ca-490c-8fe0-b8dfc88291a6", "instalacion_id": "1a00440b-a32c-4dc9-bcf8-83fb0bcd178e", "detalles": None, "normalized_detalles": ""},
    {"id": "0d5a16ae-5d34-4384-9d27-1a4fb9ba6ba5", "instalacion_id": "9181e094-a8e1-4939-8abf-c194419bea94", "detalles": None, "normalized_detalles": ""},
    {"id": "02121d7c-3bd4-4950-9da1-dcabc1943d39", "instalacion_id": "c156c5d2-e593-409a-97c8-b1c872ebb5a6", "detalles": None, "normalized_detalles": ""},
]

_PEREZ_CARRENO_UBICACION = "02121d7c-3bd4-4950-9da1-dcabc1943d39"
_SEED_API_KEY = "7c06fee1-a900-488e-9257-c22bf3056520"
_SOURCE_URL = "20260625/Hosp_Perez_Carreño/Hosp_Perez_Carreño.md"

FOUND_PEOPLE = [
    {
        "id": "f9495e77-f59c-4a45-871c-f4c46404ccac",
        "full_name": "EMILI MOSQUERA",
        "document_id": "28285779",
        "source_hash": "e4b8fa7e7d65ee9d51b356f84a1af6c0461ef86f5232f88e44821eac8c0e71e4",
    },
    {
        "id": "92ad9e68-56ba-48b0-9685-0d2c228b0716",
        "full_name": "VICTOR DIAS",
        "document_id": "11517536",
        "source_hash": "8df8ce7c480de54879c379f3e35b0a6c42551a7a35661b2c49bfa103787f228b",
    },
    {
        "id": "a0797f88-983d-4a39-9308-d5d638bcc2df",
        "full_name": "MARIA ARAQUE",
        "document_id": "28100561",
        "source_hash": "b4e206647dc5947156d22cbbf3060d39af53dcd59f9f52e7b8a8db3e894d3584",
    },
    {
        "id": "18c5de58-5f75-486b-9c4c-0919f715f1fe",
        "full_name": "MARYURI SEDENO",
        "document_id": "14194021",
        "source_hash": "836e87cab3b4474b5d47f507fcac6a0c885e50f7248aa4589b634c0e299e0cf5",
    },
    {
        "id": "d159c597-d8eb-4073-aa4c-85c762b20306",
        "full_name": "BARBARA RAMIREZ",
        "document_id": "18461886",
        "source_hash": "370129d34a8b4403fe919daf61e9be16053dbbb01ec31cc73ef62b049a9925eb",
    },
]

# Fill in the columns shared by every seeded person.
for _p in FOUND_PEOPLE:
    _p.update(
        ubicacion_id=_PEREZ_CARRENO_UBICACION,
        fallecido=False,
        source_url=_SOURCE_URL,
        status="verified",
        api_key_id=_SEED_API_KEY,
        raw={},
    )


async def _insert(session, model, rows):
    """Insert rows for a model, skipping any whose primary key already exists."""
    stmt = insert(model).values(rows).on_conflict_do_nothing(index_elements=["id"])
    result = await session.execute(stmt)
    return result.rowcount


async def _delete(session, model, rows):
    """Delete the seeded rows for a model by their known primary keys."""
    ids = [r["id"] for r in rows]
    result = await session.execute(delete(model).where(model.id.in_(ids)))
    return result.rowcount


async def reset(session) -> None:
    """Remove previously seeded rows. Child → parent order to respect FKs."""
    people = await _delete(session, FoundPerson, FOUND_PEOPLE)
    ubic = await _delete(session, Ubicacion, UBICACIONES)
    inst = await _delete(session, Instalacion, INSTALACIONES)
    keys = await _delete(session, ApiKey, API_KEYS)
    print(
        f"Reset complete (deleted): "
        f"found_people={people}, ubicaciones={ubic}, instalaciones={inst}, api_keys={keys}"
    )


async def main(do_reset: bool) -> None:
    async with AsyncSessionLocal() as session:
        if do_reset:
            await reset(session)
        # Order matters: parents before children (FK dependencies).
        keys = await _insert(session, ApiKey, API_KEYS)
        inst = await _insert(session, Instalacion, INSTALACIONES)
        ubic = await _insert(session, Ubicacion, UBICACIONES)
        people = await _insert(session, FoundPerson, FOUND_PEOPLE)
        await session.commit()

    print(
        f"Seed complete (newly inserted): "
        f"api_keys={keys}, instalaciones={inst}, ubicaciones={ubic}, found_people={people}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the database with test data.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the seeded rows (by their known ids) before re-seeding.",
    )
    args = parser.parse_args()
    asyncio.run(main(do_reset=args.reset))
