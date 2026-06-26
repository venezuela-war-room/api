import pytest
from httpx import AsyncClient

from app.config import settings


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_search_empty(client: AsyncClient):
    r = await client.get("/api/v1/found-people")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    assert "pagination" in body


@pytest.mark.asyncio
async def test_search_pagination_shape(client: AsyncClient):
    r = await client.get("/api/v1/found-people?page=1&page_size=5")
    assert r.status_code == 200
    pagination = r.json()["pagination"]
    assert pagination["page"] == 1
    assert pagination["page_size"] == 5


@pytest.mark.asyncio
async def test_search_invalid_page_size(client: AsyncClient):
    r = await client.get("/api/v1/found-people?page_size=200")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bulk_upsert_no_key(client: AsyncClient):
    r = await client.post("/api/v1/found-people/bulk", json={"people": [{"full_name": "Test"}]})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_bulk_upsert_wrong_key(client: AsyncClient):
    r = await client.post(
        "/api/v1/found-people/bulk",
        json={"people": [{"full_name": "Test"}]},
        headers={"X-Admin-Key": "wrong-key-abc"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_bulk_upsert_valid(client: AsyncClient, admin_key):
    raw_key, api_key_obj = admin_key
    payload = {
        "people": [
            {
                "full_name": "Álvarez Maikeli API Test",
                "document_id": "300454425",
                "hospital": "Hosp. José Gregorio API Test",
                "servicio": "Reporte pacientes",
                "lugar_procedencia": "La Guaira",
                "relevant_info": "Politraumatismo",
                "source_hash": "api-test-bulk-unique-1",
            },
            {
                "full_name": "Aguero Johanna API Test",
                "document_id": "37454987",
                "hospital": "Hosp. José Gregorio API Test",
                "source_hash": "api-test-bulk-unique-2",
            },
        ]
    }
    r = await client.post(
        "/api/v1/found-people/bulk",
        json=payload,
        headers={"X-Admin-Key": raw_key},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["upserted"] == 2
    assert len(body["data"]) == 2
    assert body["data"][0]["api_key"]["team_name"] == "test-team"


@pytest.mark.asyncio
async def test_bulk_upsert_too_many(client: AsyncClient, admin_key):
    raw_key, _ = admin_key
    people = [{"full_name": f"Person {i}"} for i in range(501)]
    r = await client.post(
        "/api/v1/found-people/bulk",
        json={"people": people},
        headers={"X-Admin-Key": raw_key},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_search_by_name(client: AsyncClient, admin_key):
    raw_key, _ = admin_key
    await client.post(
        "/api/v1/found-people/bulk",
        json={"people": [{"full_name": "Hernandez Carlos Search", "source_hash": "name-search-api-unique"}]},
        headers={"X-Admin-Key": raw_key},
    )
    r = await client.get("/api/v1/found-people?name=Hernandez")
    assert r.status_code == 200
    assert any("Hernandez" in p["full_name"] for p in r.json()["data"])


@pytest.mark.asyncio
async def test_search_by_document_id(client: AsyncClient, admin_key):
    raw_key, _ = admin_key
    await client.post(
        "/api/v1/found-people/bulk",
        json={"people": [{"full_name": "DocId Search API", "document_id": "11201504", "source_hash": "docid-api-search-unique"}]},
        headers={"X-Admin-Key": raw_key},
    )
    r = await client.get("/api/v1/found-people?document_id=11201504")
    assert r.status_code == 200
    assert any(p["document_id"] == "11201504" for p in r.json()["data"])


@pytest.mark.asyncio
async def test_search_by_hospital(client: AsyncClient, admin_key):
    raw_key, _ = admin_key
    await client.post(
        "/api/v1/found-people/bulk",
        json={"people": [{"full_name": "Hospital Search Test", "hospital": "Hosp. Luciani API", "source_hash": "hosp-api-search-unique"}]},
        headers={"X-Admin-Key": raw_key},
    )
    r = await client.get("/api/v1/found-people?hospital=Luciani")
    assert r.status_code == 200
    assert len(r.json()["data"]) >= 1


@pytest.mark.asyncio
async def test_get_by_id(client: AsyncClient, admin_key):
    raw_key, _ = admin_key
    create_r = await client.post(
        "/api/v1/found-people",
        json={"full_name": "Get By Id Test", "source_hash": "get-by-id-unique"},
        headers={"X-Admin-Key": raw_key},
    )
    assert create_r.status_code == 201
    person_id = create_r.json()["id"]
    r = await client.get(f"/api/v1/found-people/{person_id}")
    assert r.status_code == 200
    assert r.json()["id"] == person_id


@pytest.mark.asyncio
async def test_get_by_id_not_found(client: AsyncClient):
    r = await client.get("/api/v1/found-people/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_status(client: AsyncClient, admin_key):
    raw_key, _ = admin_key
    create_r = await client.post(
        "/api/v1/found-people",
        json={"full_name": "Status Update Test", "source_hash": "status-update-unique"},
        headers={"X-Admin-Key": raw_key},
    )
    person_id = create_r.json()["id"]
    r = await client.patch(
        f"/api/v1/found-people/{person_id}",
        json={"status": "needs_review"},
        headers={"X-Admin-Key": raw_key},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "needs_review"


@pytest.mark.asyncio
async def test_admin_create_key_no_master(client: AsyncClient):
    r = await client.post("/api/v1/admin/api-keys", json={"team_name": "test-team"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_create_and_revoke_key(client: AsyncClient):
    master_key = settings.master_admin_key
    r = await client.post(
        "/api/v1/admin/api-keys",
        json={"team_name": "new-test-team", "description": "Integration test key"},
        headers={"X-Master-Key": master_key},
    )
    assert r.status_code == 201
    body = r.json()
    assert "key" in body
    assert body["key"].startswith("tvwr_")
    assert body["team_name"] == "new-test-team"

    key_id = body["id"]
    revoke_r = await client.delete(
        f"/api/v1/admin/api-keys/{key_id}",
        headers={"X-Master-Key": master_key},
    )
    assert revoke_r.status_code == 200

    revoked_key = body["key"]
    use_r = await client.post(
        "/api/v1/found-people/bulk",
        json={"people": [{"full_name": "Should Fail"}]},
        headers={"X-Admin-Key": revoked_key},
    )
    assert use_r.status_code == 401


@pytest.mark.asyncio
async def test_admin_list_keys(client: AsyncClient):
    master_key = settings.master_admin_key
    r = await client.get("/api/v1/admin/api-keys", headers={"X-Master-Key": master_key})
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    for item in r.json():
        assert "key" not in item
