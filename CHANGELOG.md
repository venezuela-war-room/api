# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

## [0.1.0] — 2026-06-26

### Added

**Core API**
- `GET /health` — liveness check with DB connectivity ping
- `GET /api/v1/found-people` — public search endpoint with filters: `q`, `name`, `document_id`, `hospital`, `procedencia`, `status`, `page`, `page_size`
- `GET /api/v1/found-people/{id}` — retrieve a single record by UUID
- `POST /api/v1/found-people` — create a single record (requires `X-Admin-Key`)
- `POST /api/v1/found-people/bulk` — idempotent bulk upsert of 1–500 records (requires `X-Admin-Key`)
- `PATCH /api/v1/found-people/{id}` — update record status (requires `X-Admin-Key`)
- `DELETE /api/v1/found-people` — soft-delete by `source_url`, sets `status=removed` (requires `X-Admin-Key`)

**Multi-tenant API key management**
- `POST /api/v1/admin/api-keys` — generate a new team API key (requires `X-Master-Key`)
- `GET /api/v1/admin/api-keys` — list all keys showing prefix and team name only (requires `X-Master-Key`)
- `DELETE /api/v1/admin/api-keys/{id}` — revoke a key (requires `X-Master-Key`)

**Database schema**
- `hospitals` table — normalized healthcare facility names with `unaccent` deduplication
- `servicios` table — hospital wards/sections, deduplicated per hospital
- `api_keys` table — per-team hashed credentials with revocation support
- `found_people` table — main person registry with FK links to all three tables
- PostgreSQL extensions: `pgcrypto`, `pg_trgm`, `unaccent`
- GIN trigram index on `full_name` for fast fuzzy search
- Indexes on `document_id`, `status`, `updated_at`, `hospital_id`, `api_key_id`

**Ingestion**
- `source_hash`-based deduplication via `ON CONFLICT DO UPDATE` — safe to re-ingest the same data
- Auto-generated `source_hash` from `sha256(full_name|document_id|hospital)` when not provided by caller
- `find-or-create` logic for hospitals and servicios on every ingest call
- `api_key_id` recorded on every `found_people` row for source attribution

**Search**
- Accent-insensitive name and hospital search via `unaccent() ILIKE`
- Exact match on `document_id` (non-digit characters stripped on input)
- Full-text `q` param searches name, procedencia, and relevant_info

**Validation (Pydantic v2)**
- All string inputs: NFKC unicode normalization, control-character stripping, whitespace collapse
- `document_id`: non-digit characters stripped, must contain at least one digit
- `status`: restricted to `verified`, `citizen_report`, `needs_review`, `removed`
- Bulk list: min 1, max 500 records
- `page_size`: max 100
- Age: 0–150 range

**Infrastructure**
- `Dockerfile` using `python:3.12-slim` with uv for dependency installation
- `docker-compose.yml` with `postgres:16` and health-checked startup
- `railway.toml` for Railway deployment with auto-migration on startup
- `.github/workflows/ci.yml` — GitHub Actions CI running tests against a real PostgreSQL service

**Scripts**
- `scripts/import_csv.py` — batch importer for `consolidado.csv` from `ecrespo/OCR-data_Terremoto_Venezuela_24062026`; batches of 200, maps all 7 CSV columns to the API schema

**Tests**
- 15 Pydantic unit tests (no DB dependency)
- 8 CRUD integration tests
- 15 HTTP tests covering auth, search, bulk ingest, key lifecycle

### Contributors
- [@jesusareyesv](https://github.com/jesusareyesv) — initial implementation

[0.1.0]: https://github.com/jesusareyesv/terremoto-venezuela-war-room-api/releases/tag/v0.1.0
