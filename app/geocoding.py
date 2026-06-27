"""OpenStreetMap Nominatim geocoding client.

Pure HTTP client — no DB. Resolves a facility name to an address + coordinates. The
background worker (``app/geocoding_worker.py``) drives this; the request path no longer
calls it. Every call distinguishes three outcomes so the worker can decide whether to
retry:

- **matched** — OSM returned a result → ``GeocodeOutcome(result=<...>, completed=True)``
- **no match** — OSM responded 200 with an empty list → ``(result=None, completed=True)``
- **transient** — timeout / network / 5xx → ``(result=None, completed=False)`` (retry later)

⚠️ The public ``nominatim.openstreetmap.org`` endpoint forbids parallel requests
(~1 req/sec, identifying ``User-Agent`` required). ``geocode_batch`` bounds concurrency
with ``settings.geocoding_concurrency`` (default 1) and waits ``geocoding_request_delay``
between dispatches; raise concurrency only against a self-hosted/commercial instance.
"""

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeocodeResult:
    direccion: str | None
    lat: float | None
    lon: float | None


@dataclass(frozen=True)
class GeocodeOutcome:
    """Result plus whether OSM gave a definitive answer (vs. a transient failure)."""

    result: GeocodeResult | None
    completed: bool


# A definitive "OSM had nothing" — safe to stop retrying.
NO_MATCH = GeocodeOutcome(result=None, completed=True)
# A transient failure — leave the row pending so it is retried.
TRANSIENT = GeocodeOutcome(result=None, completed=False)


def _parse(payload: list) -> GeocodeOutcome:
    if not payload:
        return NO_MATCH
    first = payload[0]
    direccion = first.get("display_name") or None
    try:
        lat = float(first["lat"]) if first.get("lat") is not None else None
        lon = float(first["lon"]) if first.get("lon") is not None else None
    except (TypeError, ValueError):
        lat = lon = None
    if direccion is None and lat is None and lon is None:
        return NO_MATCH
    return GeocodeOutcome(result=GeocodeResult(direccion=direccion, lat=lat, lon=lon), completed=True)


async def geocode_one(client: httpx.AsyncClient, nombre: str) -> GeocodeOutcome:
    """Geocode a single facility name. Never raises — failures become TRANSIENT."""
    params = {
        "q": f"{nombre}, Venezuela",
        "format": "jsonv2",
        "limit": "1",
        "addressdetails": "0",
    }
    if settings.geocoding_country_codes:
        params["countrycodes"] = settings.geocoding_country_codes
    try:
        resp = await client.get(f"{settings.nominatim_base_url}/search", params=params)
        resp.raise_for_status()
        return _parse(resp.json())
    except (httpx.HTTPError, ValueError) as exc:  # network, timeout, 5xx, bad JSON
        logger.warning("Geocoding failed (transient) for %r: %s", nombre, exc)
        return TRANSIENT


async def geocode_batch(names: Iterable[str]) -> dict[str, GeocodeOutcome]:
    """Geocode many names (deduped, bounded concurrency). Returns ``{name: outcome}``.

    Returns ``{}`` immediately when geocoding is disabled (keeps tests offline).
    """
    if not settings.geocoding_enabled:
        return {}

    unique = sorted({n for n in names if n})
    if not unique:
        return {}

    semaphore = asyncio.Semaphore(max(1, settings.geocoding_concurrency))
    headers = {"User-Agent": settings.nominatim_user_agent}

    async with httpx.AsyncClient(timeout=settings.geocoding_timeout, headers=headers) as client:

        async def _run(name: str) -> tuple[str, GeocodeOutcome]:
            async with semaphore:
                outcome = await geocode_one(client, name)
                # Politeness delay so a serial (concurrency=1) batch stays ≤1 req/sec.
                if settings.geocoding_request_delay > 0:
                    await asyncio.sleep(settings.geocoding_request_delay)
                return name, outcome

        results = await asyncio.gather(*(_run(n) for n in unique))

    return dict(results)
