# Terremoto Venezuela War Room API

REST API for searching and managing records of people found or hospitalized after the **Venezuela earthquake of June 24, 2026**. Built to consolidate data from multiple volunteer teams into a single queryable source of truth.

## Overview

Multiple organizations and volunteers are transcribing hospital lists, OCR-processing handwritten registries, and submitting citizen reports. This API provides:

- A **public search endpoint** to look up people by name, cédula, hospital, place of origin, and more
- A **multi-tenant ingestion system** with per-team API keys so every record is traceable to its source
- **Normalized facility data** — hospitals and wards (servicios) are deduplicated across all submissions
- **Idempotent bulk upsert** — the same record submitted twice updates rather than duplicates

### Primary data sources

| Source | Description |
|---|---|
| [edwinvrgs/found-people-ve-bot](https://github.com/edwinvrgs/found-people-ve-bot) | Telegram bot ingesting official and citizen reports |
| [ecrespo/OCR-data_Terremoto_Venezuela_24062026](https://github.com/ecrespo/OCR-data_Terremoto_Venezuela_24062026) | OCR-transcribed handwritten hospital lists (3,500+ people, 16 facilities) |

---

## Tech Stack

- **Runtime:** Python 3.12, [uv](https://docs.astral.sh/uv/) package manager
- **Framework:** FastAPI 0.115+ with async SQLAlchemy 2.0
- **Database:** PostgreSQL 16 (`pg_trgm`, `unaccent`, `pgcrypto` extensions)
- **Migrations:** Alembic
- **Validation:** Pydantic v2
- **Deployment:** Railway
- **CI:** GitHub Actions

---

## Database Schema

```
instalaciones     — deduplicated facilities (hospitals, shelters, morgues, …) + address/coords
ubicaciones       — a specific location within or without a facility (ward, floor, ad-hoc address)
api_keys          — per-team ingestion credentials
found_people      — the main registry (FK to ubicaciones, api_keys)
```

Every `found_people` record carries an `api_key_id` so you always know which team submitted it.

Facility addresses (`direccion`, `lat`, `lon` on `instalaciones`) are filled asynchronously by a
background geocoding worker — see the [ETL / data-flow diagram](docs/etl-diagram.md).

See the full [ER diagram](docs/er-diagram.md) for column details, relationships, and indexes.

---

## API Reference

### Public endpoints (no auth)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check + DB ping |
| GET | `/api/v1/found-people` | Search with filters and pagination |
| GET | `/api/v1/found-people/{id}` | Get a single record by UUID |

**Search query parameters:**

| Param | Description |
|---|---|
| `q` | Full-text search across name, procedencia, and notes |
| `name` | Search by person name (accent-insensitive, partial match) |
| `document_id` | Exact match on cédula (digits only, non-digits stripped) |
| `hospital` | Partial match on hospital name |
| `procedencia` | Partial match on place of origin |
| `status` | Filter by status (`verified`, `citizen_report`, `needs_review`, `removed`) |
| `page` | Page number (default: 1, max: 500) |
| `page_size` | Results per page (default: 10, max: 100) |

**Response shape:**
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
      "api_key": { "id": "uuid", "team_name": "ocr-ecrespo", "key_prefix": "tvwr_abc1" },
      "created_at": "2026-06-26T...",
      "updated_at": "2026-06-26T..."
    }
  ],
  "pagination": { "page": 1, "page_size": 10, "total": 3569, "total_pages": 357 }
}
```

### Protected endpoints (`X-Admin-Key` header required)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/found-people` | Create a single record |
| POST | `/api/v1/found-people/bulk` | Upsert 1–500 records (idempotent by `source_hash`) |
| PATCH | `/api/v1/found-people/{id}` | Update record status |
| DELETE | `/api/v1/found-people` | Soft-delete by `source_url` (sets `status=removed`) |

**Bulk request body:**
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

If `source_hash` is omitted it is auto-generated from `sha256(full_name|document_id|ubicacion_actual|tipo_instalacion)`.

**Bulk response:** `created` counts new rows, `updated` counts rows that already existed (matched on `source_hash`) and were refreshed.
```json
{ "created": 42, "updated": 3, "data": [...] }
```

### Master admin endpoints (`X-Master-Key` header required)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/admin/api-keys` | Create a new team API key (returned once) |
| GET | `/api/v1/admin/api-keys` | List all keys (prefix + team name only, never raw key) |
| DELETE | `/api/v1/admin/api-keys/{id}` | Revoke a key |

---

## Running Locally

### With Docker (recommended)

```bash
# 1. Copy env file and set your master key
cp .env.example .env

# 2. Start Postgres + API
docker compose up

# API is available at http://localhost:8000
# Interactive docs at http://localhost:8000/docs
```

### Without Docker

```bash
# Requires PostgreSQL 16 running locally with pgcrypto, pg_trgm, unaccent extensions

cp .env.example .env
# Edit DATABASE_URL and MASTER_ADMIN_KEY in .env

uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

### Create your first API key

```bash
curl -X POST http://localhost:8000/api/v1/admin/api-keys \
  -H "X-Master-Key: your-master-key" \
  -H "Content-Type: application/json" \
  -d '{"team_name": "my-team", "description": "Initial key"}'
```

The response contains the full key — **save it immediately, it is not recoverable**.

### Import OCR data

```bash
# Download consolidado.csv from ecrespo/OCR-data_Terremoto_Venezuela_24062026
uv run python scripts/import_csv.py consolidado.csv \
  --admin-key tvwr_... \
  --api-url http://localhost:8000
```

### Seed test data

For a small, predictable dataset (5 hospitals + ward locations + 5 sample people)
to develop or test against, run the seed script. It talks to the database directly,
so point `DATABASE_URL` at your target — for the docker compose Postgres:

```bash
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/terremoto" \
  uv run python scripts/seed_test_data.py
```

The script is **idempotent** (`ON CONFLICT (id) DO NOTHING`), so re-running it is
safe and reports how many rows were newly inserted. Pass `--reset` to delete the
seeded rows first (scoped to their known ids, child → parent order) for a clean
wipe-and-reseed:

```bash
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/terremoto" \
  uv run python scripts/seed_test_data.py --reset
```

> The seeded `api_key` is a placeholder — its hash matches no real key, so it only
> satisfies the `found_people` foreign key. It will not authenticate API requests.

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL async URL | `postgresql+asyncpg://postgres:postgres@localhost:5432/terremoto` |
| `MASTER_ADMIN_KEY` | Secret for managing API keys | `change-me-in-production` |
| `CORS_ORIGINS` | JSON list of allowed origins | `["*"]` |
| `DEBUG` | Enable SQLAlchemy query logging | `false` |
| `GEOCODING_ENABLED` | Master switch for OpenStreetMap address lookup | `true` |
| `GEOCODING_WORKER_ENABLED` | Run the in-app background geocoding worker | `true` |
| `GEOCODING_WORKER_INTERVAL` | Idle seconds between worker cycles when nothing is pending | `60` |
| `GEOCODING_BATCH_SIZE` | Facilities geocoded per worker cycle | `10` |
| `GEOCODING_CONCURRENCY` | Parallel Nominatim requests (raise only for self-hosted) | `1` |
| `GEOCODING_REQUEST_DELAY` | Seconds between Nominatim calls (politeness) | `1.0` |
| `NOMINATIM_BASE_URL` | Geocoding endpoint | public OSM Nominatim |
| `NOMINATIM_USER_AGENT` | Identifying User-Agent (required by Nominatim policy) | project default |

---

## Running Tests

```bash
# Schema unit tests only (no DB needed)
uv run pytest tests/test_schemas.py -v

# All tests (requires a test PostgreSQL DB)
# Set DATABASE_URL to point at terremoto_test database
uv run pytest tests/ -v
```

---

## Deployment (Railway)

1. Create a new Railway project and add a **PostgreSQL** plugin
2. Connect this repository
3. Set environment variables in Railway:
   - `DATABASE_URL` (Railway provides this automatically from the plugin)
   - `MASTER_ADMIN_KEY`
4. Railway picks up `railway.toml` and runs:
   ```
   alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```

---

## Project Structure

```
app/
  main.py         FastAPI app factory and middleware
  config.py       Settings via pydantic-settings
  database.py     Async SQLAlchemy engine and session dependency
  models.py       SQLAlchemy ORM models
  schemas.py      Pydantic v2 request/response schemas
  auth.py         API key and master key authentication dependencies
  crud.py         Database operations (search, upsert, find-or-create)
  geocoding.py    OpenStreetMap Nominatim client (pure HTTP)
  geocoding_worker.py  Background worker that fills facility addresses
  routers/
    health.py     GET /health
    people.py     /api/v1/found-people routes
    admin.py      /api/v1/admin/api-keys routes
migrations/
  versions/001_initial.py            Initial schema + extensions
  versions/002_instalacion_coords.py lat/lon + geocoding queue (geocoded_at)
scripts/
  import_csv.py            One-shot CSV importer
  seed_test_data.py        Seed a small fixed test dataset (--reset to wipe + reseed)
  backfill_addresses.py    Drain the geocoding queue on demand
  dedup_facilities.py      Merge duplicate facilities by canonical name
docs/
  er-diagram.md   Entity-relationship diagram
  etl-diagram.md  Ingestion + geocoding data-flow diagram
tests/
  test_schemas.py          Pydantic unit tests
  test_crud.py             DB integration tests
  test_api.py              Full HTTP tests
  test_geocoding.py        Nominatim client unit tests
  test_geocoding_worker.py Worker queue/outcome tests
  test_docs.py             OpenAPI/Swagger surface tests
```

---

## License

MIT
