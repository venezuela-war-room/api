import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.models import FoundPerson, Instalacion, Ubicacion
from app.schemas import PersonCreate, SearchParams


@pytest.mark.parametrize(
    "variant",
    [
        "Hospital Domingo Luciani",
        "HOSPITAL DOMINGO LUCIANI",
        "Hospital Domingo Lucianí",
        "Hosp. Domingo Luciani",
        "Hospital Dr. Domingo Luciani",
        "Hospital Domingo Luciani (El Llanito)",
        "Hospital de Domingo Luciani",
    ],
)
def test_normalize_facility_collapses_variants(variant):
    assert crud._normalize_facility(variant) == crud._normalize_facility("Hospital Domingo Luciani")


def test_normalize_facility_keeps_distinct_places():
    # The facility-type word is preserved, so these stay different keys.
    assert crud._normalize_facility("Hospital Vargas") != crud._normalize_facility("Clínica Vargas")


@pytest.mark.asyncio
async def test_find_or_create_instalacion_dedup(db: AsyncSession):
    i1 = await crud.find_or_create_instalacion(db, "hospital", "Hosp. José Gregorio Hernández")
    i2 = await crud.find_or_create_instalacion(db, "hospital", "Hosp. José Gregorio Hernández")
    assert i1.id == i2.id


@pytest.mark.asyncio
async def test_find_or_create_instalacion_same_nombre_different_tipo(db: AsyncSession):
    i1 = await crud.find_or_create_instalacion(db, "hospital", "Centro Vargas")
    i2 = await crud.find_or_create_instalacion(db, "centro_medico", "Centro Vargas")
    assert i1.id != i2.id


@pytest.mark.asyncio
async def test_find_or_create_instalacion_pending_when_no_direccion(db: AsyncSession):
    inst = await crud.find_or_create_instalacion(db, "hospital", "Hosp. Sin Direccion CRUD")
    # No address → left in the geocoding queue for the background worker.
    assert inst.direccion is None
    assert inst.geocoded_at is None


@pytest.mark.asyncio
async def test_find_or_create_instalacion_done_when_direccion_supplied(db: AsyncSession):
    inst = await crud.find_or_create_instalacion(
        db, "hospital", "Hosp. Con Direccion CRUD", direccion="Av. Principal, Caracas"
    )
    await db.refresh(inst)
    # Client supplied the address → marked done so the worker skips it.
    assert inst.direccion == "Av. Principal, Caracas"
    assert inst.geocoded_at is not None


@pytest.mark.asyncio
async def test_find_or_create_ubicacion_dedup(db: AsyncSession):
    instalacion = await crud.find_or_create_instalacion(db, "hospital", "Hospital de Prueba CRUD")
    u1 = await crud.find_or_create_ubicacion(db, instalacion.id, "Emergencias")
    u2 = await crud.find_or_create_ubicacion(db, instalacion.id, "Emergencias")
    assert u1.id == u2.id


@pytest.mark.asyncio
async def test_find_or_create_ubicacion_no_instalacion(db: AsyncSession):
    u = await crud.find_or_create_ubicacion(db, None, "Calle Principal Casa 5 Catia")
    assert u.instalacion_id is None
    assert u.detalles == "Calle Principal Casa 5 Catia"


@pytest.mark.asyncio
async def test_upsert_new_person(db: AsyncSession):
    payload = PersonCreate(
        full_name="Aguero Johanna",
        document_id="37454987",
        age=26,
        ubicacion_actual="Hosp. Magallanes Test",
        tipo_instalacion="hospital",
        ubicacion_detalles="Sala de emergencias",
        lugar_procedencia="Nuevo Jesús",
    )
    person, inserted = await crud.upsert_person(db, payload)
    assert inserted is True
    assert person.full_name == "Aguero Johanna"
    assert person.ubicacion is not None
    assert person.ubicacion.instalacion is not None
    assert person.ubicacion.instalacion.nombre == "Hosp. Magallanes Test"
    assert person.ubicacion.instalacion.tipo == "hospital"
    assert person.ubicacion.detalles == "Sala de emergencias"
    assert person.fallecido is False
    await db.commit()


@pytest.mark.asyncio
async def test_upsert_fallecido_flag(db: AsyncSession):
    payload = PersonCreate(
        full_name="Persona Fallecida Test",
        source_hash="fallecido-unique-hash-test",
        fallecido=True,
        ubicacion_actual="Morgue Central Test",
        tipo_instalacion="morgue",
    )
    person, _ = await crud.upsert_person(db, payload)
    assert person.fallecido is True
    assert person.ubicacion.instalacion.tipo == "morgue"
    await db.commit()


@pytest.mark.asyncio
async def test_upsert_same_hash_updates(db: AsyncSession):
    payload = PersonCreate(
        full_name="Bermúdez Génesis",
        document_id="20925605",
        ubicacion_actual="Hosp. Update Test",
        source_hash="fixed-hash-update-test-v2",
    )
    p1, inserted1 = await crud.upsert_person(db, payload)
    await db.commit()
    assert inserted1 is True  # first call is a genuine insert

    updated = PersonCreate(
        full_name="Bermúdez Génesis Updated",
        document_id="20925605",
        ubicacion_actual="Hosp. Update Test",
        source_hash="fixed-hash-update-test-v2",
        relevant_info="Fractura de miembros",
    )
    p2, inserted2 = await crud.upsert_person(db, updated)
    await db.commit()
    assert inserted2 is False  # second call hit the conflict and updated

    assert p1.id == p2.id
    assert p2.full_name == "Bermúdez Génesis Updated"
    assert p2.relevant_info == "Fractura de miembros"


@pytest.mark.asyncio
async def test_search_by_name(db: AsyncSession):
    payload = PersonCreate(full_name="Cantero Tunilda Search Test", source_hash="search-name-test-v2")
    await crud.upsert_person(db, payload)
    await db.commit()

    params = SearchParams(name="Cantero")
    results, _ = await crud.search_people(db, params)
    assert any("Cantero" in p.full_name for p in results)


@pytest.mark.asyncio
async def test_search_by_document_id(db: AsyncSession):
    payload = PersonCreate(
        full_name="Arrieta José DocId Test",
        document_id="15720959",
        source_hash="docid-search-v2",
    )
    await crud.upsert_person(db, payload)
    await db.commit()

    params = SearchParams(document_id="15720959")
    results, _ = await crud.search_people(db, params)
    assert any(p.document_id == "15720959" for p in results)


@pytest.mark.asyncio
async def test_search_by_tipo_instalacion(db: AsyncSession):
    payload = PersonCreate(
        full_name="Albergue Person Test",
        ubicacion_actual="Albergue Petare Test",
        tipo_instalacion="albergue",
        source_hash="albergue-tipo-search-test",
    )
    await crud.upsert_person(db, payload)
    await db.commit()

    params = SearchParams(tipo_instalacion="albergue")
    results, _ = await crud.search_people(db, params)
    assert any(
        p.ubicacion and p.ubicacion.instalacion and p.ubicacion.instalacion.tipo == "albergue"
        for p in results
    )


@pytest.mark.asyncio
async def test_search_fallecido(db: AsyncSession):
    payload = PersonCreate(
        full_name="Fallecido Search Test",
        fallecido=True,
        source_hash="fallecido-search-unique",
    )
    await crud.upsert_person(db, payload)
    await db.commit()

    params = SearchParams(fallecido=True)
    results, _ = await crud.search_people(db, params)
    assert all(p.fallecido for p in results)


@pytest.mark.asyncio
async def test_soft_delete(db: AsyncSession):
    payload = PersonCreate(
        full_name="Delete Test Person",
        source_url="https://example.com/delete-test-v2",
        source_hash="soft-delete-v2",
    )
    await crud.upsert_person(db, payload)
    await db.commit()

    deleted = await crud.soft_delete_by_source_url(db, "https://example.com/delete-test-v2")
    await db.commit()
    assert deleted >= 1

    params = SearchParams(name="Delete Test Person")
    results, _ = await crud.search_people(db, params)
    assert all(p.status != "removed" for p in results)


@pytest.mark.asyncio
async def test_merge_instalacion_reassigns_and_merges_wards(db: AsyncSession):
    source = await crud.find_or_create_instalacion(db, "hospital", "Merge Source Hosp")
    target = await crud.find_or_create_instalacion(db, "hospital", "Merge Target Hosp")

    src_only = await crud.find_or_create_ubicacion(db, source.id, "Sala Unica Source")
    src_shared = await crud.find_or_create_ubicacion(db, source.id, "Sala Compartida")
    tgt_shared = await crud.find_or_create_ubicacion(db, target.id, "Sala Compartida")

    p_only = FoundPerson(full_name="Person Only", source_hash="merge-only-v1", ubicacion_id=src_only.id)
    p_shared = FoundPerson(full_name="Person Shared", source_hash="merge-shared-v1", ubicacion_id=src_shared.id)
    db.add_all([p_only, p_shared])
    await db.flush()

    await crud.merge_instalacion(db, source, target)
    await db.commit()

    # Source facility is gone.
    assert (await db.execute(select(Instalacion).where(Instalacion.id == source.id))).scalar_one_or_none() is None

    # The source-only ward was repointed to the target; its person travels with it.
    moved = (await db.execute(select(Ubicacion).where(Ubicacion.id == src_only.id))).scalar_one()
    assert moved.instalacion_id == target.id
    assert (await db.execute(select(FoundPerson).where(FoundPerson.id == p_only.id))).scalar_one().ubicacion_id == src_only.id

    # The colliding "Sala Compartida" ward was merged: source ward deleted, person repointed.
    assert (await db.execute(select(Ubicacion).where(Ubicacion.id == src_shared.id))).scalar_one_or_none() is None
    assert (await db.execute(select(FoundPerson).where(FoundPerson.id == p_shared.id))).scalar_one().ubicacion_id == tgt_shared.id


@pytest.mark.asyncio
async def test_merge_instalacion_backfills_missing_fields(db: AsyncSession):
    source = await crud.find_or_create_instalacion(db, "hospital", "Backfill Source Hosp", direccion="Calle 1")
    source.lat, source.lon, source.osm_id = 10.5, -66.9, "way/999"
    target = await crud.find_or_create_instalacion(db, "hospital", "Backfill Target Hosp")
    await db.flush()

    await crud.merge_instalacion(db, source, target)
    await db.commit()

    await db.refresh(target)
    assert target.direccion == "Calle 1"
    assert target.lat == 10.5
    assert target.osm_id == "way/999"
