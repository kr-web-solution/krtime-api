#!/bin/sh
set -e

echo "[attendguard-api] Alembic migrate..."
alembic upgrade head

WORKERS="${UVICORN_WORKERS:-2}"
echo "[attendguard-api] Uvicorn workers=${WORKERS}"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WORKERS}"
