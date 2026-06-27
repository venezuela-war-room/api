from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.analytics import analytics_middleware, capture_event, shutdown_analytics
from app.config import settings
from app.routers import admin, health, people

API_DESCRIPTION = """
Shared search layer for tracking people found, hospitalized, or sheltered after the
**Venezuela earthquake of June 24, 2026**. Multiple volunteer teams ingest records;
this API deduplicates and exposes them through a single search surface.

## Authentication

Two header-based API keys are used (click **Authorize** to set them):

- **`X-Admin-Key`** — any active team key. Required for ingestion and status changes
  (`POST`, `PATCH`, `DELETE` on `/found-people`). Issued by an administrator.
- **`X-Master-Key`** — the master secret. Required only for API-key lifecycle routes
  under `/admin/api-keys`.

Read endpoints (search and lookup) are public and need no key.

## Ingestion notes

- All writes go through an upsert keyed on `source_hash` (SHA-256). Re-sending the same
  record updates it in place instead of creating a duplicate.
- Facility names (`ubicacion_actual`) are normalized and deduplicated server-side.
"""

TAGS_METADATA = [
    {
        "name": "health",
        "description": "Liveness/readiness probe. Verifies the API can reach the database.",
    },
    {
        "name": "found-people",
        "description": (
            "Search, look up, and ingest records of found people. "
            "Reads are public; writes require `X-Admin-Key`."
        ),
    },
    {
        "name": "admin",
        "description": "API-key lifecycle (create, list, revoke). Requires `X-Master-Key`.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    capture_event("server_started")
    try:
        yield
    finally:
        await shutdown_analytics()


app = FastAPI(
    title="Terremoto Venezuela War Room API",
    description=API_DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=TAGS_METADATA,
    contact={"name": "Terremoto Venezuela War Room"},
    license_info={"name": "MIT"},
    swagger_ui_parameters={"persistAuthorization": True, "displayRequestDuration": True},
)

app.middleware("http")(analytics_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Redirect the bare root to the interactive Swagger UI."""
    return RedirectResponse(url="/docs")


app.include_router(health.router)
app.include_router(people.router)
app.include_router(admin.router)
