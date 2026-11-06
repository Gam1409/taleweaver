#!/usr/bin/env sh
# Docker entrypoint: run Alembic migrations, then start the application.
# Using /bin/sh (POSIX) for maximum compatibility with slim Python images.

set -e

WORKERS="${WEB_CONCURRENCY:-1}"
if [ "$WORKERS" != "1" ]; then
    echo "[entrypoint] TaleWeaver requires a single worker (WEB_CONCURRENCY=1): session leases and visual jobs are process-local." >&2
    exit 64
fi

# A new mount must not silently replace an existing installation with an empty DB.
SQLITE_TARGET="${TALEWEAVER_SQLITE_FILE:-}"
SQLITE_LEGACY="${TALEWEAVER_LEGACY_SQLITE_FILE:-}"
if [ -n "$SQLITE_TARGET" ] && [ "${DATABASE_URL:-}" = "sqlite+aiosqlite:///$SQLITE_TARGET" ] \
    && [ -f "$SQLITE_LEGACY" ] && [ ! -f "$SQLITE_TARGET" ]; then
    echo "[entrypoint] Existing SQLite database found. Stop the old server and migrate it to the separate SQLite volume; see docs/docker-storage.md. No migration or server request was started." >&2
    exit 78
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
