# Venezuela War Room API

[![CI](https://github.com/venezuela-war-room/api/actions/workflows/ci.yml/badge.svg)](https://github.com/venezuela-war-room/api/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

REST API for searching, ingesting, and managing records of people found, missing, hospitalized, or otherwise reported after the **Venezuela earthquake of June 24, 2026**.

The API consolidates records from volunteer teams, OCR datasets, citizen reports, and partner tools into a single queryable source of truth while preserving source traceability and protecting operational controls behind API keys.

> **Data-safety principle:** make public search useful, keep ingestion accountable, avoid leaking secrets or unnecessary sensitive data, and preserve source attribution for every record.

---

## What this API provides

- Public search for affected people by name, cédula/document, hospital/facility, origin, status, and general text query.
- Protected ingestion endpoints for trusted teams using per-team API keys.
- Idempotent bulk upserts to refresh source records without duplicating them.
- Normalized facilities and locations to reduce duplicated hospital/ward names.
- Master-admin endpoints to issue, list, and revoke ingestion keys.
- Background geocoding for facilities using OpenStreetMap/Nominatim.
- Alembic migrations, CI checks, Docker support, and Railway deployment config.

---

## Primary data sources

| Source | Description |
| --- | --- |
| [edwinvrgs/found-people-ve-bot](https://github.com/edwinvrgs/found-people-ve-bot) | Telegram bot ingesting official and citizen reports |
| [ecrespo/OCR-data_Terremoto_Venezuela_24062026](https://github.com/ecrespo/OCR-data_Terremoto_Venezuela_24062026) | OCR-transcribed handwritten hospital lists |

---

## Tech stack

- **Runtime:** Python 3.12
- **Package manager:** [uv](https://docs.astral.sh/uv/)
- **Framework:** FastAPI 0.115+
- **Database:** PostgreSQL 16 with `pg_trgm`, `unaccent`, and `pgcrypto`
- **ORM:** SQLAlchemy 2.0 async
- **Migrations:** Alembic
- **Validation:** Pydantic v2
- **Deployment:** Railway / Docker
- **CI:** GitHub Actions

---

## Database model

```text
instalaciones  — deduplicated facilities: hospitals, shelters, morgues, etc.
ubicaciones    — specific locations inside/outside a facility: ward, floor, address
api_keys       — per-team ingestion credentials and attribution
found_people   — main searchable registry, linked to ubicaciones and api_keys
```

Every `found_people` record carries an `api_key_id`, so submitted data remains attributable to the team/source that created or updated it.

Facility addresses (`direccion`, `lat`, `lon`) are filled asynchronously by the geocoding worker. See:

- [`docs/er-diagram.md`](docs/er-diagram.md)
- [`docs/etl-diagram.md`](docs/etl-diagram.md)

---

## API reference

### Public endpoints

No authentication required.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness check and database ping |
| `GET` | `/api/v1/found-people` | Search records with filters and pagination |
| `GET` | `/api/v1/found-people/{id}` | Get one record by UUID |

Search query parameters:

| Parameter | Description |
| --- | --- |
| `q` | Full-text search across name, origin/procedencia, and notes |
| `name` | Accent-insensitive partial match on person name |
| `document_id` | Exact cédula/document match; non-digits are stripped |
| `hospital` | Partial match on hospital/facility name |
| `procedencia` | Partial match on place of origin |
| `status` | Filter by status: `verified`, `citizen_report`, `needs_review`, `removed` |
| `page` | Page number; default `1`, max `500` |
| `page_size` | Results per page; default `10`, max `100` |

Example response:

```json
{
  "data": [
    {
      "id": "uuid",
      "full_name": "Álvarez Maikeli",
      "document_id": "300454425",
      "age": null,
      "hospital": { "id": "uuid", "name": "Hosp. José Gregorio Hernández" },
      "servicio": { "id": "uuid", "name": "Reporte pacientes atendidos" },
      "lugar_procedencia": "La Guaira",
      "relevant_info": "Politraumatismo",
      "status": "verified",
      "api_key": {
        "id": "uuid",
        "team_name": "ocr-ecrespo",
        "key_prefix": "tvwr_abc1"
      },
      "created_at": "2026-06-26T00:00:00Z",
      "updated_at": "2026-06-26T00:00:00Z"
    }
  ],
  "pagination": { "page": 1, "page_size": 10, "total": 3569, "total_pages": 357 }
}
```

### Protected ingestion endpoints

Require `X-Admin-Key`.

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/found-people` | Create one record |
| `POST` | `/api/v1/found-people/bulk` | Upsert 1–500 records idempotently by `source_hash` |
| `PATCH` | `/api/v1/found-people/{id}` | Update record status/details |
| `DELETE` | `/api/v1/found-people` | Soft-delete records by `source_url` by setting `status=removed` |

Bulk request example:

```json
{
  "people": [
    {
      "full_name": "Aguero Johanna",
      "document_id": "37454987",
      "age": 26,
      "hospital": "Hosp. José Gregorio Hernández (Magallanes)",
      "servicio": "Registro hospitalario (dropbox 26JUN)",
      "lugar_procedencia": "Nuevo Jesús",
      "relevant_info": "Fuente: Consolidado dropbox 26JUN26",
      "source_url": "https://github.com/ecrespo/...",
      "source_hash": "optional-dedup-key",
      "status": "verified"
    }
  ]
}
```

If `source_hash` is omitted, the API generates a fallback person key from `document_id` when present, otherwise from the normalized name. Location is intentionally excluded so the same person reported in multiple wards or source rows updates one public record instead of creating duplicates.

Bulk response:

```json
{ "created": 42, "updated": 3, "data": [] }
```

### Master-admin endpoints

Require `X-Master-Key`.

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/admin/api-keys` | Create a new team API key; raw key is returned once |
| `GET` | `/api/v1/admin/api-keys` | List keys by prefix/team only; raw keys are never returned |
| `DELETE` | `/api/v1/admin/api-keys/{id}` | Revoke a key |

---

## Running locally

### Option A: Docker

```bash
cp .env.example .env
# Edit MASTER_ADMIN_KEY and any local overrides.
docker compose up
```

API: <http://localhost:8000>

OpenAPI docs: <http://localhost:8000/docs>

### Option B: uv + local PostgreSQL

Requires PostgreSQL 16 with `pgcrypto`, `pg_trgm`, and `unaccent` available.

```bash
cp .env.example .env
# Edit DATABASE_URL and MASTER_ADMIN_KEY.
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

---

## Create an ingestion API key

```bash
curl -X POST http://localhost:8000/api/v1/admin/api-keys \
  -H "X-Master-Key: your-master-key" \
  -H "Content-Type: application/json" \
  -d '{"team_name": "my-team", "description": "Initial key"}'
```

The response contains the full key. Save it immediately; it is not recoverable later.

---

## Import and seed data

### Import OCR data

```bash
uv run python scripts/import_csv.py consolidado.csv \
  --admin-key tvwr_... \
  --api-url http://localhost:8000
```

### Seed test data

```bash
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/terremoto" \
  uv run python scripts/seed_test_data.py
```

Reset and reseed:

```bash
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/terremoto" \
  uv run python scripts/seed_test_data.py --reset
```

The seeded `api_key` is a placeholder and will not authenticate API requests.

---

## Environment variables

| Variable | Description | Default |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL async URL | `postgresql+asyncpg://postgres:postgres@localhost:5432/terremoto` |
| `MASTER_ADMIN_KEY` | Secret for managing API keys | `change-me-in-production` |
| `CORS_ORIGINS` | JSON list of allowed origins | `["*"]` |
| `DEBUG` | Enable SQLAlchemy query logging | `false` |
| `GEOCODING_ENABLED` | Master switch for OpenStreetMap address lookup | `true` |
| `GEOCODING_WORKER_ENABLED` | Run the in-app background geocoding worker | `true` |
| `GEOCODING_WORKER_INTERVAL` | Idle seconds between worker cycles when nothing is pending | `60` |
| `GEOCODING_BATCH_SIZE` | Facilities geocoded per worker cycle | `10` |
| `GEOCODING_CONCURRENCY` | Parallel Nominatim requests; keep low for public Nominatim | `1` |
| `GEOCODING_REQUEST_DELAY` | Seconds between Nominatim calls | `1.0` |
| `NOMINATIM_BASE_URL` | Geocoding endpoint | Public OSM Nominatim |
| `NOMINATIM_USER_AGENT` | Identifying user agent required by Nominatim policy | Project default |
| `POSTHOG_API_KEY` | Optional analytics key | Empty |

Never commit real `.env` files, production database URLs, API keys, master keys, or exports with personal data.

---

## Validation

```bash
uv run ruff check .
uv run python -m compileall app migrations tests
```

Schema-only tests:

```bash
uv run pytest tests/test_schemas.py -v
```

Full test suite, with `DATABASE_URL` pointing to a test PostgreSQL database:

```bash
uv run pytest tests/ -v --asyncio-mode=auto
```

Migration integrity check:

```bash
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
```

---

## Deployment: Railway

1. Create a Railway project and add PostgreSQL.
2. Connect this repository.
3. Set environment variables:
   - `DATABASE_URL` from Railway PostgreSQL
   - `MASTER_ADMIN_KEY`
   - Production-safe `CORS_ORIGINS`
   - Optional geocoding/analytics variables
4. Railway uses `railway.toml` to run migrations and start the API.

---

## Project structure

```text
app/
  main.py              FastAPI app, middleware, router mounting
  config.py            Settings via pydantic-settings
  database.py          Async SQLAlchemy engine/session dependency
  models.py            SQLAlchemy ORM models
  schemas.py           Pydantic request/response schemas
  auth.py              API-key and master-key dependencies
  crud.py              Search, upsert, and find-or-create operations
  geocoding.py         OpenStreetMap/Nominatim client
  geocoding_worker.py  Background facility geocoding worker
  routers/
    health.py          GET /health
    people.py          /api/v1/found-people routes
    admin.py           /api/v1/admin/api-keys routes
migrations/
  versions/            Alembic migrations
scripts/
  import_csv.py        CSV importer through protected API
  seed_test_data.py    Small deterministic seed dataset
  backfill_addresses.py
  dedup_facilities.py
docs/
  er-diagram.md
  etl-diagram.md
tests/
  test_api.py
  test_crud.py
  test_docs.py
  test_geocoding.py
  test_geocoding_worker.py
  test_schemas.py
```

---

## Contributing

Contributions are welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request.

Use the pull request template, include validation results, and call out any endpoint, migration, ingestion, privacy, or deployment impact.

---

## Security

Please do not open public issues for vulnerabilities, leaked secrets, auth bypasses, ingestion abuse, or personal-data exposure. Follow [`SECURITY.md`](SECURITY.md).

---

## Code of conduct

This project supports disaster-relief coordination. Contributors are expected to communicate respectfully and protect affected people’s dignity and privacy. See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

---

## License

MIT — see [`LICENSE`](LICENSE).
