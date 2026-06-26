import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.schemas import PersonCreate, SearchParams


@pytest.mark.asyncio
async def test_find_or_create_hospital_dedup(db: AsyncSession):
    h1 = await crud.find_or_create_hospital(db, "Hosp. José Gregorio Hernández")
    h2 = await crud.find_or_create_hospital(db, "Hosp. José Gregorio Hernández")
    assert h1.id == h2.id


@pytest.mark.asyncio
async def test_find_or_create_hospital_accent_insensitive(db: AsyncSession):
    h1 = await crud.find_or_create_hospital(db, "Hospital Vargas")
    h2 = await crud.find_or_create_hospital(db, "Hospital Vargas")
    assert h1.id == h2.id


@pytest.mark.asyncio
async def test_find_or_create_servicio_dedup(db: AsyncSession):
    hospital = await crud.find_or_create_hospital(db, "Hospital de Prueba")
    s1 = await crud.find_or_create_servicio(db, hospital.id, "Emergencias")
    s2 = await crud.find_or_create_servicio(db, hospital.id, "Emergencias")
    assert s1.id == s2.id


@pytest.mark.asyncio
async def test_find_or_create_servicio_different_hospitals(db: AsyncSession):
    h1 = await crud.find_or_create_hospital(db, "Hospital A Test")
    h2 = await crud.find_or_create_hospital(db, "Hospital B Test")
    s1 = await crud.find_or_create_servicio(db, h1.id, "UCI")
    s2 = await crud.find_or_create_servicio(db, h2.id, "UCI")
    assert s1.id != s2.id


@pytest.mark.asyncio
async def test_upsert_new_person(db: AsyncSession):
    payload = PersonCreate(
        full_name="Aguero Johanna",
        document_id="37454987",
        age=26,
        hospital="Hosp. Magallanes Test",
        lugar_procedencia="Nuevo Jesús",
    )
    person, inserted = await crud.upsert_person(db, payload)
    assert inserted is True
    assert person.full_name == "Aguero Johanna"
    assert person.hospital is not None
    assert person.hospital.name == "Hosp. Magallanes Test"
    await db.commit()


@pytest.mark.asyncio
async def test_upsert_same_hash_updates(db: AsyncSession):
    payload = PersonCreate(
        full_name="Bermúdez Génesis",
        document_id="20925605",
        hospital="Hosp. Update Test",
        source_hash="fixed-hash-for-update-test",
    )
    p1, _ = await crud.upsert_person(db, payload)
    await db.commit()

    updated_payload = PersonCreate(
        full_name="Bermúdez Génesis Updated",
        document_id="20925605",
        hospital="Hosp. Update Test",
        source_hash="fixed-hash-for-update-test",
        relevant_info="Fractura de miembros",
    )
    p2, _ = await crud.upsert_person(db, updated_payload)
    await db.commit()

    assert p1.id == p2.id
    assert p2.full_name == "Bermúdez Génesis Updated"
    assert p2.relevant_info == "Fractura de miembros"


@pytest.mark.asyncio
async def test_search_by_name(db: AsyncSession):
    payload = PersonCreate(full_name="Cantero Tunilda Search Test", source_hash="search-name-test-unique")
    await crud.upsert_person(db, payload)
    await db.commit()

    params = SearchParams(name="Cantero")
    results, total = await crud.search_people(db, params)
    assert any("Cantero" in p.full_name for p in results)


@pytest.mark.asyncio
async def test_search_by_document_id(db: AsyncSession):
    payload = PersonCreate(
        full_name="Arrieta José DocId Test",
        document_id="15720959",
        source_hash="docid-search-unique-test",
    )
    await crud.upsert_person(db, payload)
    await db.commit()

    params = SearchParams(document_id="15720959")
    results, _ = await crud.search_people(db, params)
    assert any(p.document_id == "15720959" for p in results)


@pytest.mark.asyncio
async def test_soft_delete(db: AsyncSession):
    payload = PersonCreate(
        full_name="Delete Test Person",
        source_url="https://example.com/delete-test",
        source_hash="soft-delete-unique-hash",
    )
    await crud.upsert_person(db, payload)
    await db.commit()

    deleted = await crud.soft_delete_by_source_url(db, "https://example.com/delete-test")
    await db.commit()
    assert deleted >= 1

    params = SearchParams(name="Delete Test Person")
    results, _ = await crud.search_people(db, params)
    assert all(p.status != "removed" for p in results)

    params_with_removed = SearchParams(name="Delete Test Person", status="removed")
    results_removed, total = await crud.search_people(db, params_with_removed)
