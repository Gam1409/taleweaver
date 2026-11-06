#!/usr/bin/env bash
# Launch both services with the installed project environment (Bash 3.2+).
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

UPDATE_REPOSITORY=true
while [ "$#" -gt 0 ]; do
    case "$1" in
        --no-update) UPDATE_REPOSITORY=false ;;
        --help) echo "Usage: ./run.sh [--no-update]"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 64 ;;
    esac
    shift
done

if [ "$UPDATE_REPOSITORY" = true ] && [ -e .git ]; then
    echo "[*] Checking for repository updates..."
    if ! git pull --ff-only; then
        echo "[!] Could not update; continuing with the current checkout." >&2
    fi
fi

RUNNER_PYTHON=""
resolve_python() {
    local candidate
    for candidate in .venv/bin/python .venv/bin/python3 venv/bin/python venv/bin/python3 .venv/Scripts/python.exe venv/Scripts/python.exe; do
        if [ -x "$candidate" ]; then
            RUNNER_PYTHON="$candidate"
            return 0
        fi
    done
    if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
        RUNNER_PYTHON="$VIRTUAL_ENV/bin/python"
        return 0
    fi
    if command -v poetry >/dev/null 2>&1; then
        candidate="$(poetry env info --executable 2>/dev/null)" || candidate=""
        if [ -n "$candidate" ] && [ -x "$candidate" ]; then
            RUNNER_PYTHON="$candidate"
            return 0
        fi
    fi
    return 1
}

setup_complete() {
    resolve_python || return 1
    [ -f .env ] || { [ -n "${SECRET_KEY:-}" ] && [ -n "${ENCRYPTION_KEY:-}" ]; } || return 1
    [ -f frontend/node_modules/.bin/vite ] || return 1
    command -v npm >/dev/null 2>&1
}

if ! setup_complete; then
    echo "[!] Setup is incomplete. Install the project environment and frontend dependencies."
    if [ ! -t 0 ]; then
        echo "Run ./setup.sh --skip-start or complete the Poetry setup before starting." >&2
        exit 1
    fi
    read -r -p "Run setup.sh now? [y/N]: " RUNNER_SETUP
    case "$RUNNER_SETUP" in
        y|Y|yes|YES) bash ./setup.sh --skip-start ;;
        *) exit 1 ;;
    esac
    if ! setup_complete; then
        echo "[!] Setup is still incomplete; no services were started." >&2
        exit 1
    fi
fi

# Each service owns a process group, including npm's Vite child. This works
# with macOS's Bash 3.2 and does not depend on the newer wait -n builtin.
set -m
BACKEND_PID=""
FRONTEND_PID=""
stop_group() {
    local pid="$1" signal_name="$2"
    [ -n "$pid" ] || return 0
    kill -s "$signal_name" -- "-$pid" 2>/dev/null || true
}
group_alive() {
    [ -n "$1" ] && kill -0 -- "-$1" 2>/dev/null
}
cleanup() {
    trap - EXIT
    trap '' INT TERM
    stop_group "$BACKEND_PID" TERM
    stop_group "$FRONTEND_PID" TERM
    local attempt
    for attempt in {1..20}; do
        if ! group_alive "$BACKEND_PID" && ! group_alive "$FRONTEND_PID"; then break; fi
        sleep 0.1
    done
    stop_group "$BACKEND_PID" KILL
    stop_group "$FRONTEND_PID" KILL
    [ -z "$BACKEND_PID" ] || wait "$BACKEND_PID" 2>/dev/null || true
    [ -z "$FRONTEND_PID" ] || wait "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "[*] Starting TaleWeaver with $RUNNER_PYTHON"
"$RUNNER_PYTHON" -m backend.main &
BACKEND_PID=$!
(cd frontend && exec npm run dev) &
FRONTEND_PID=$!
echo "[*] Press Ctrl+C to stop both services."

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
    sleep 0.1
done
RUNNER_STATUS=0
if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    wait "$BACKEND_PID" || RUNNER_STATUS=$?
else
    wait "$FRONTEND_PID" || RUNNER_STATUS=$?
fi
exit "$RUNNER_STATUS"
