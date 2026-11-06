#!/usr/bin/env sh
# Docker entrypoint: run Alembic migrations, then start the application.
# Using /bin/sh (POSIX) for maximum compatibility with slim Python images.

set -e

WORKERS="${WEB_CONCURRENCY:-1}"
if [ "$WORKERS" != "1" ]; then
    echo "[entrypoint] TaleWeaver requires a single worker (WEB_CONCURRENCY=1): session leases and visual jobs are process-local." >&2
    exit 64
fi

echo "[entrypoint] Running database migrations..."
python -m alembic upgrade head

TIMEOUT="${GUNICORN_TIMEOUT:-120}"
GRACEFUL_TIMEOUT="${GUNICORN_GRACEFUL_TIMEOUT:-30}"

echo "[entrypoint] Starting TaleWeaver backend with Gunicorn (${WORKERS} workers)..."
exec gunicorn backend.main:app \
	--worker-class uvicorn.workers.UvicornWorker \
	--workers "${WORKERS}" \
	--bind 0.0.0.0:8000 \
	--timeout "${TIMEOUT}" \
	--graceful-timeout "${GRACEFUL_TIMEOUT}"
