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

### Facility vs. free-text — only real places become `instalaciones`
`ubicacion_actual` is only turned into a facility when `crud._looks_like_facility` says it names a real, geocodeable place (facility keyword like *hospital/albergue/cdi*, or a short keyword-less name like "Pérez Carreño"). Sentence-like free text (`"Está en el área de pediatría del Pérez carreño"`) is routed instead into a `ubicacion` with `instalacion_id = NULL`, folded into `detalles` via `crud._combine_detalles` — kept as location info, never geocoded. Two layers enforce this:
1. **Ingestion gate** (`_looks_like_facility`): deterministic keyword/prose heuristic in `upsert_person`. Junk never enters the facilities table or the geocode queue.
2. **Geocode confirmation** (backstop): if a facility that slipped past the gate gets a definitive OSM **no-match** AND has no facility keyword, the worker calls `crud.demote_instalacion_to_detalle` (folds the name into `detalles`, repoints people, deletes the facility). A named "Hospital …" with no OSM match is **kept** as an unconfirmed facility (`osm_id` NULL) — OSM gaps must not destroy real places.

### Facility dedup — one real place = one `instalaciones` row
Two complementary layers keep a facility like "Hospital Domingo Luciani" from fanning out across teams:

1. **Deterministic normalization** (`crud._normalize_facility`): strip accents/case, drop parentheticals, expand abbreviations (`Hosp.`→`hospital`), drop honorifics/connector stopwords — the facility-TYPE word is kept so `Hospital Vargas` ≠ `Clínica Vargas`. `find_or_create_instalacion` dedups on `(tipo, normalized_nombre)` (unique constraint `uq_instalacion_tipo_nombre`). This collapses abbreviation/format variants at ingestion.
2. **Geocode-anchored identity** (`instalaciones.osm_id`): the worker geocodes the **canonical** name and stores the stable OSM `"{osm_type}/{osm_id}"`. Variants that normalization missed (typos, word order) but resolve to the same OSM place are **merged** by the worker via `crud.merge_instalacion`. A partial unique index `uq_instalaciones_osm_id` enforces one facility per OSM place. This can merge across `tipo` (same real place).

`crud.merge_instalacion(source, target)` folds one facility into another: it reassigns `ubicaciones`/`found_people` (merging colliding wards via the `(instalacion_id, normalized_detalles)` rule) and deletes the source — using **Core** updates/deletes (ORM cascade would lazy-load in the async session). `scripts/dedup_facilities.py [--apply]` runs the normalization-merge over existing rows (needed once after a normalization change).

`find_or_create_ubicacion` still uses the plain `_normalize` for ward `detalles`.

### Facility address geocoding (OpenStreetMap) — background worker
`instalaciones` rows carry `direccion`, `lat`, `lon`, and `geocoded_at`. **Geocoding is off the request path** — ingestion never calls OpenStreetMap. See the data-flow in `docs/etl-diagram.md`.

- **Queue marker:** `geocoded_at IS NULL` ⟺ "needs geocoding", backed by the partial index `ix_instalaciones_pending_geocode`. On ingestion, `crud.find_or_create_instalacion` stores a client-supplied `direccion` (and sets `geocoded_at = now()`); with no address it leaves `geocoded_at` NULL so the worker picks it up.
- **Worker:** `app/geocoding_worker.py` `run_worker()` is started in the `app/main.py` lifespan (gated by `geocoding_worker_enabled` + `geocoding_enabled`). Each cycle `claim_pending` selects `WHERE geocoded_at IS NULL ... FOR UPDATE SKIP LOCKED` (multi-process safe), `geocode_batch`es the **normalized** names (Nominatim fails on raw abbreviations like "Hosp." but resolves "hospital …"), and writes results.
- **Outcomes** (`GeocodeOutcome`): matched → write `direccion`/`lat`/`lon`/`osm_id` + stamp `geocoded_at` (and if another facility already holds that `osm_id`, **merge** into it); no-match (HTTP 200 empty) → stamp `geocoded_at` only (stop retrying); transient (timeout/5xx) → leave `geocoded_at` NULL (retried next cycle).
- `app/geocoding.py` is a **pure HTTP client** (no DB). `app/geocoding_worker.py` owns the DB/queue logic. `crud.py` stays DB-only; routers do a plain upsert (no network).
- ⚠️ The **public** Nominatim endpoint forbids parallel requests (~1 req/sec, identifying `User-Agent` required). `geocoding_concurrency` defaults to `1` and `geocoding_request_delay` to `1.0s`; raise concurrency only against a self-hosted/commercial instance via `NOMINATIM_BASE_URL`.
- **Manual drain:** `uv run python scripts/backfill_addresses.py [--limit N] [--dry-run]` runs the same `process_pending_batch` (e.g. without the web app, or when the worker is disabled).
- Tests stay offline: an autouse fixture in `conftest.py` sets `geocoding_enabled = False` (and the worker isn't started — httpx `ASGITransport` skips lifespan); tests that exercise geocoding monkeypatch `geocode_one`/`geocode_batch` or `app.geocoding_worker.geocode_batch`.

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
| `GEOCODING_ENABLED` | `true`/`false` — master switch for OpenStreetMap address lookup (default `true`) |
| `GEOCODING_WORKER_ENABLED` | Run the in-app background geocoding worker (default `true`) |
| `GEOCODING_WORKER_INTERVAL` | Idle seconds between worker cycles when nothing is pending (default `60`) |
| `GEOCODING_BATCH_SIZE` | Facilities geocoded per worker cycle (default `10`) |
| `NOMINATIM_BASE_URL` | Geocoding endpoint (default public OSM Nominatim) |
| `NOMINATIM_USER_AGENT` | Identifying UA string — **required** by Nominatim policy |
| `GEOCODING_TIMEOUT` | Per-request timeout seconds (default `5.0`) |
| `GEOCODING_CONCURRENCY` | Parallel geocode requests (default `1`; raise only for self-hosted Nominatim) |
| `GEOCODING_REQUEST_DELAY` | Seconds between Nominatim calls (default `1.0`) |
| `GEOCODING_COUNTRY_CODES` | Bias results by country (default `ve`) |

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
| `Hospital / Área` | `ubicacion_actual` |
| `Nombre` | `full_name` |
| `Edad` | `age` |
| `Cédula` | `document_id` |
| `Procedencia / Zona` | `lugar_procedencia` |
| `Servicio / Lista` | `ubicacion_detalles` |
| `Nota` | `relevant_info` |

`scripts/import_csv.py` does **not** set `tipo_instalacion` — the `"Hospital / Área"` column mixes real facility names with free-text descriptions, so the API's `_looks_like_facility` gate (not a blanket `hospital` tag) decides whether each value becomes a facility or a `ubicacion` detail.

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
