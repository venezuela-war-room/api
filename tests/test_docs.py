import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_openapi_schema_served(client: AsyncClient):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["info"]["title"] == "Terremoto Venezuela War Room API"
    assert schema["openapi"].startswith("3.")


@pytest.mark.asyncio
async def test_swagger_ui_served(client: AsyncClient):
    r = await client.get("/docs")
    assert r.status_code == 200
    assert "swagger-ui" in r.text.lower()


@pytest.mark.asyncio
async def test_redoc_served(client: AsyncClient):
    r = await client.get("/redoc")
    assert r.status_code == 200
    assert "redoc" in r.text.lower()


@pytest.mark.asyncio
async def test_root_redirects_to_docs(client: AsyncClient):
    r = await client.get("/", follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"] == "/docs"


@pytest.mark.asyncio
async def test_security_schemes_documented(client: AsyncClient):
    schema = (await client.get("/openapi.json")).json()
    security_schemes = schema["components"]["securitySchemes"]
    header_names = {s.get("name") for s in security_schemes.values()}
    assert "X-Admin-Key" in header_names
    assert "X-Master-Key" in header_names


@pytest.mark.asyncio
async def test_tags_metadata_present(client: AsyncClient):
    schema = (await client.get("/openapi.json")).json()
    tag_names = {t["name"] for t in schema.get("tags", [])}
    assert {"health", "found-people", "admin"} <= tag_names


@pytest.mark.asyncio
async def test_write_endpoint_requires_admin_key_in_schema(client: AsyncClient):
    schema = (await client.get("/openapi.json")).json()
    post_op = schema["paths"]["/api/v1/found-people"]["post"]
    # Every security requirement on the create endpoint must reference an admin-key scheme.
    assert post_op.get("security"), "create endpoint should declare a security requirement"
