# CLAUDE.md — Terremoto Venezuela War Room API

## Project purpose

FastAPI + PostgreSQL API tracking people found/hospitalized after the Venezuela earthquake of June 24, 2026. Multiple volunteer teams submit records; this API is the shared search layer.

## Commands

```bash
uv sync                                  # install/sync dependencies
uv run uvicorn app.main:app --reload     # dev server on :8000
uv run alembic upgrade head              # apply migrations
uv run alembic revision -m "description" # create a new migration
uv run pytest tests/test_schemas.py -v  # unit tests (no DB)
uv run pytest tests/ -v                 # all tests (needs Postgres)
docker compose up                        # full local stack
```

## Architecture

```
app/config.py     pydantic-settings — DATABASE_URL, MASTER_ADMIN_KEY, CORS_ORIGINS
app/database.py   async SQLAlchemy engine + AsyncSession dependency (get_db)
app/models.py     Hospital, Servicio, ApiKey, FoundPerson ORM models
app/schemas.py    Pydantic v2 — PersonCreate, PersonBulkCreate, SearchParams, ApiKey*
app/auth.py       require_admin (DB key hash lookup), require_master (env var check)
app/crud.py       all DB operations — search_people, upsert_person, find_or_create_*
app/routers/      health.py / people.py / admin.py
migrations/       Alembic; initial migration in versions/001_initial.py
scripts/          import_csv.py — one-shot CSV importer
tests/            conftest.py sets up a test DB session; fixtures share session-scoped engine
```

## Key patterns

### Deduplication
Every record has a `source_hash` (SHA-256). Upserts use `ON CONFLICT (source_hash) DO UPDATE`. If the caller doesn't provide `source_hash`, `crud.py` generates it from `sha256(full_name|document_id|hospital)`.

### Facility normalization
Before inserting a `found_people` row, `crud.find_or_create_hospital` and `crud.find_or_create_servicio` normalize the name (NFKD → strip combining chars → lowercase) and do a SELECT before INSERT. This keeps hospitals and servicios deduplicated across teams.

### Auth
- `X-Admin-Key`: any active row in `api_keys` (matched by SHA-256 hash). The resolved `ApiKey` object is attached to `request.state.api_key` and its `id` is written to `found_people.api_key_id`.
- `X-Master-Key`: compared directly to `settings.master_admin_key` (env var). Only used for key lifecycle routes.

### Search
- `document_id`: exact match, digits-only
- `name` / `q`: `func.unaccent(col).ilike(f"%{term}%")`
- `hospital`: JOIN on `hospitals` table then `unaccent ILIKE`
- Default filter: `status != 'removed'` (soft-deleted records hidden unless `status=removed` is explicit)

## Database

PostgreSQL 16. Required extensions (created in migration 001):
- `pgcrypto` — `gen_random_uuid()`
- `pg_trgm` — GIN index on `full_name` for trigram search
- `unaccent` — accent-insensitive text matching

Test database: `terremoto_test`. Set `DATABASE_URL` env var to point at it when running tests.

## Environment variables

| Var | Notes |
|---|---|
| `DATABASE_URL` | Must use `postgresql+asyncpg://` scheme |
| `MASTER_ADMIN_KEY` | Long random secret — required in production |
| `CORS_ORIGINS` | JSON list, e.g. `["https://myapp.com"]` |
| `DEBUG` | Set `true` to echo SQL queries |

## API documentation (Swagger / OpenAPI)

FastAPI auto-generates the OpenAPI schema and serves interactive docs. There is no
separate spec file to maintain — the docs are produced from the route decorators and
Pydantic schemas, so keeping them rich is part of writing each endpoint.

- **Swagger UI:** `/docs` — **ReDoc:** `/redoc` — **raw schema:** `/openapi.json`
- `/` redirects to `/docs`.
- Top-level metadata (title, description, tag descriptions, contact/license, Swagger UI
  options) lives in `app/main.py` (`API_DESCRIPTION`, `TAGS_METADATA`, the `FastAPI(...)`
  call).
- Auth shows up as two **Authorize** schemes: `AdminKey` (`X-Admin-Key`) and `MasterKey`
  (`X-Master-Key`). These are declared via `APIKeyHeader(..., scheme_name=...)` in
  `app/auth.py`. The distinct `scheme_name` on each is **required** — without it both
  collapse into one scheme and one of the keys disappears from the docs.
- Each route carries a `summary`, `description`, and documented non-2xx `responses=`.
- Request bodies carry `model_config["json_schema_extra"]["examples"]` in `app/schemas.py`
  so "Try it out" is pre-filled.
- Docs/OpenAPI behavior is covered by `tests/test_docs.py`.

**On every change, update the Swagger docs and the tests to match:**

- New/changed route → add or update its `summary`, `description`, tag, and `responses=`,
  and adjust `tests/test_docs.py` / `tests/test_api.py` accordingly.
- New/changed request schema → update its `json_schema_extra` example.
- New auth scheme or header → give it a unique `scheme_name` and assert it in
  `tests/test_docs.py`.
- Run `uv run pytest tests/ -v` before considering the change done.

## Adding a new endpoint

1. Add route in `app/routers/people.py` (or `admin.py`) — include `summary`,
   `description`, tag, and documented `responses=` for Swagger
2. Add Pydantic schema in `app/schemas.py` if new input/output shape — add a
   `json_schema_extra` example for any request body
3. Add DB logic in `app/crud.py`
4. Add test cases in `tests/test_api.py`, and update `tests/test_docs.py` if the
   OpenAPI surface (tags, security schemes, documented paths) changed
5. If schema changes, run `uv run alembic revision -m "..."` and fill in `upgrade()`/`downgrade()`
6. Run `uv run pytest tests/ -v`

## What NOT to do

- Do not bypass `upsert_person` for ingestion — it handles hospital/servicio resolution and dedup
- Do not store raw API keys — only SHA-256 hashes go in the DB
- Do not use synchronous SQLAlchemy — all DB calls must `await`
- Do not add `.env` to git — it contains secrets

## Data source field mapping

| CSV column (ecrespo OCR) | API field |
|---|---|
| `Hospital / Área` | `hospital` |
| `Nombre` | `full_name` |
| `Edad` | `age` |
| `Cédula` | `document_id` |
| `Procedencia / Zona` | `lugar_procedencia` |
| `Servicio / Lista` | `servicio` |
| `Nota` | `relevant_info` |

| Bot field (edwinvrgs) | API field |
|---|---|
| `fullName` | `full_name` |
| `documentId` | `document_id` |
| `location` | `hospital` or `lugar_procedencia` |
| `relevantInfo` | `relevant_info` |
| `sourceUrl` | `source_url` |
| `sourceHash` | `source_hash` |
| `status` | `status` |
| `raw` | `raw` |
