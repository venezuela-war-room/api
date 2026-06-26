#!/bin/sh
set -e

/app/.venv/bin/alembic upgrade head
exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
