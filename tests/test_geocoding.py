import httpx
import pytest

from app import geocoding
from app.config import settings


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_geocode_one_matched():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"display_name": "Hospital X, Caracas, Venezuela", "lat": "10.5", "lon": "-66.9"}],
        )

    async with _mock_client(handler) as client:
        outcome = await geocoding.geocode_one(client, "Hospital X")

    assert outcome.completed is True
    assert outcome.result is not None
    assert outcome.result.direccion == "Hospital X, Caracas, Venezuela"
    assert outcome.result.lat == 10.5
    assert outcome.result.lon == -66.9


@pytest.mark.asyncio
async def test_geocode_one_builds_osm_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"display_name": "X", "lat": "1", "lon": "2", "osm_type": "way", "osm_id": 228913258}],
        )

    async with _mock_client(handler) as client:
        outcome = await geocoding.geocode_one(client, "Hospital Domingo Luciani")
    assert outcome.result.osm_id == "way/228913258"


@pytest.mark.asyncio
async def test_geocode_one_osm_id_none_when_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"display_name": "X", "lat": "1", "lon": "2"}])

    async with _mock_client(handler) as client:
        outcome = await geocoding.geocode_one(client, "Albergue Sin OSM")
    assert outcome.result is not None
    assert outcome.result.osm_id is None


@pytest.mark.asyncio
async def test_geocode_one_no_match_is_completed():
    async with _mock_client(lambda req: httpx.Response(200, json=[])) as client:
        outcome = await geocoding.geocode_one(client, "Nowhere")
    assert outcome.completed is True  # definitive — don't retry
    assert outcome.result is None


@pytest.mark.asyncio
async def test_geocode_one_http_error_is_transient():
    async with _mock_client(lambda req: httpx.Response(503)) as client:
        outcome = await geocoding.geocode_one(client, "Hospital X")
    assert outcome.completed is False  # transient — retry later
    assert outcome.result is None


@pytest.mark.asyncio
async def test_geocode_batch_returns_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "geocoding_enabled", False)
    assert await geocoding.geocode_batch(["Hospital X"]) == {}


@pytest.mark.asyncio
async def test_geocode_batch_dedups_names(monkeypatch):
    monkeypatch.setattr(settings, "geocoding_enabled", True)
    monkeypatch.setattr(settings, "geocoding_request_delay", 0)
    calls: list[str] = []

    async def fake_geocode_one(client, nombre):
        calls.append(nombre)
        return geocoding.GeocodeOutcome(
            result=geocoding.GeocodeResult(direccion=f"addr {nombre}", lat=1.0, lon=2.0),
            completed=True,
        )

    monkeypatch.setattr(geocoding, "geocode_one", fake_geocode_one)

    result = await geocoding.geocode_batch(["Hospital X", "Hospital X", "Hospital Y", ""])

    assert sorted(calls) == ["Hospital X", "Hospital Y"]  # deduped, empties dropped
    assert set(result) == {"Hospital X", "Hospital Y"}
    assert result["Hospital X"].result.direccion == "addr Hospital X"


@pytest.mark.asyncio
async def test_geocode_batch_includes_transient_outcomes(monkeypatch):
    monkeypatch.setattr(settings, "geocoding_enabled", True)
    monkeypatch.setattr(settings, "geocoding_request_delay", 0)

    async def fake_geocode_one(client, nombre):
        if nombre == "Down":
            return geocoding.TRANSIENT
        return geocoding.GeocodeOutcome(geocoding.GeocodeResult("addr", 1.0, 2.0), completed=True)

    monkeypatch.setattr(geocoding, "geocode_one", fake_geocode_one)

    result = await geocoding.geocode_batch(["Up", "Down"])
    assert result["Up"].completed is True
    assert result["Down"].completed is False  # surfaced so the worker leaves it pending
