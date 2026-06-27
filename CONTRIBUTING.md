# Contributing

Thanks for helping improve the Venezuela War Room API. This project supports disaster-relief coordination and search for people affected by the June 24, 2026 earthquake in Venezuela, so changes must prioritize data safety, traceability, and operational reliability.

## Before you start

- Read `README.md` for setup, endpoints, and architecture notes.
- Check existing issues and pull requests to avoid duplicate work.
- Do not commit real API keys, master keys, production database URLs, personal datasets, exports, or logs with sensitive personal information.
- For security/privacy issues, follow `SECURITY.md` instead of opening a public issue.

## Local development

```bash
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

The Docker path is also supported:

```bash
docker compose up
```

## Development standards

- Keep API behavior explicit and documented in `README.md` or OpenAPI-facing schemas when endpoints change.
- Preserve source traceability: records should remain linked to the API key/team and source metadata that created them.
- Keep ingestion idempotent whenever possible; duplicate data should update existing records instead of creating noise.
- Avoid logging raw personal data, API keys, master keys, or complete request bodies that may contain sensitive data.
- Treat migrations as part of the public contract. They must apply cleanly from scratch and remain reversible unless clearly justified.
- Prefer small, focused pull requests with clear operational impact.

## Validation checklist

Run the relevant checks before opening a pull request:

```bash
uv run ruff check .
uv run python -m compileall app migrations tests
uv run pytest tests/ -v --asyncio-mode=auto
```

For database changes, also run migrations against a local test database:

```bash
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
```

## Pull request expectations

A good PR includes:

- What changed and why.
- Any endpoint, schema, migration, or environment variable changes.
- Validation commands run locally.
- Privacy/security considerations if the change touches personal data, ingestion, authentication, CORS, geocoding, or logs.
- Backfill/import instructions when data migrations or scripts are involved.

## Data handling

This API can contain names, IDs, medical/location context, source URLs, and volunteer-submitted reports. When in doubt, minimize data exposure, keep auditability, and ask maintainers before broadening public access.
