# Contributors

## Maintainer

- [@jesusareyesv](https://github.com/jesusareyesv)

---

## How to Contribute

This is an active humanitarian relief project. Contributions that improve data coverage, search quality, ingestion reliability, or deployment simplicity are especially welcome.

### Getting started

```bash
git clone https://github.com/jesusareyesv/terremoto-venezuela-war-room-api
cd terremoto-venezuela-war-room-api

cp .env.example .env          # set DATABASE_URL and MASTER_ADMIN_KEY
docker compose up -d db       # start Postgres
uv sync                       # install dependencies
uv run alembic upgrade head   # create tables
uv run uvicorn app.main:app --reload
```

Run the test suite:

```bash
uv run pytest tests/test_schemas.py -v          # no DB required
uv run pytest tests/ -v                         # full suite, needs Postgres
```

### Types of contributions

| Type | What to do |
|---|---|
| **Bug fix** | Open an issue first if the bug isn't obvious; then submit a PR |
| **New search filter** | Add query param in `routers/people.py`, filter logic in `crud.py`, test in `test_api.py` |
| **New data source importer** | Add a script under `scripts/`, modeled after `import_csv.py` |
| **Schema change** | Generate a new Alembic revision: `uv run alembic revision -m "description"` |
| **Performance** | Profile first, include before/after query plans in the PR |
| **Docs** | PRs welcome for README, endpoint docs, or deployment guides |

### Pull request checklist

- [ ] `uv run pytest tests/test_schemas.py` passes
- [ ] If touching DB queries, `uv run pytest tests/` passes against a real Postgres instance
- [ ] No new raw SQL — use SQLAlchemy expressions
- [ ] No secrets committed — double-check `.env` is in `.gitignore`
- [ ] New endpoints include a test in `test_api.py`
- [ ] Schema changes include a new migration under `migrations/versions/`

### Coding conventions

- **Package manager:** `uv` — do not use pip directly
- **Python version:** 3.12+
- **Async everywhere:** all DB operations go through `AsyncSession`; never use the sync engine
- **Validation at the edge:** all incoming data is validated by Pydantic schemas in `app/schemas.py` before reaching `crud.py`
- **No raw keys in DB:** API keys are stored as SHA-256 hashes only
- **Deduplication:** use `source_hash` and the existing `upsert_person` in `crud.py`; do not bypass it

### Adding a new data source

1. Obtain or build a mapping from your source's fields to `PersonCreate` fields:

   | Source field | `PersonCreate` field |
   |---|---|
   | Name / Nombre | `full_name` |
   | Cédula / ID | `document_id` |
   | Hospital / Área | `hospital` |
   | Servicio / Ward | `servicio` |
   | Procedencia / Zone | `lugar_procedencia` |
   | Notes / Nota | `relevant_info` |

2. Write a script under `scripts/` (see `import_csv.py` as reference)
3. Request an API key from the maintainer for your team: `POST /api/v1/admin/api-keys`
4. Run your import against the staging or production endpoint

### Reporting issues

- **Missing person record:** Open an issue with the source URL so it can be re-ingested
- **Wrong data / OCR error:** Open an issue with the correct value and the record UUID if known
- **Security concern:** Email the maintainer directly rather than opening a public issue

---

Thank you for helping in this relief effort.
