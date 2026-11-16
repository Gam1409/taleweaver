#!/usr/bin/env bash
# TaleWeaver Setup Script (Bash)
# This script sets up the Python environment, database, and frontend dependencies.

set -e

# Parse arguments
SKIP_START=false
CONCORDIA=false
INSTALL_EXTRAS=()
for arg in "$@"; do
    if [ "$arg" == "--concordia" ]; then
        CONCORDIA=true
        INSTALL_EXTRAS=(--extras concordia)
    fi
    if [ "$arg" == "--skip-start" ]; then
        SKIP_START=true
    fi
done

echo "--- TaleWeaver Setup ---"

# 1. Environment Variables (.env)
if [ ! -f .env ]; then
    echo "[*] Creating .env from .env.example..."
    cp .env.example .env
fi

if ! grep -q "PROJECT_NAME=" .env; then
    sed -i '1i PROJECT_NAME="TaleWeaver"' .env
else
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' 's/PROJECT_NAME=.*/PROJECT_NAME="TaleWeaver"/' .env
    else
        sed -i 's/PROJECT_NAME=.*/PROJECT_NAME="TaleWeaver"/' .env
    fi
fi

# 2. Dependency Management (Poetry)
echo "[*] Installing Python dependencies, including LanceDB, with Poetry..."
if command -v poetry &> /dev/null; then
    echo "[+] Using system Poetry..."
    poetry install "${INSTALL_EXTRAS[@]}"
    RUN_CMD="poetry run"
    PYTHON_CMD="poetry run python"
else
    echo "[*] Poetry not found in PATH. Checking virtual environment (venv)..."
    if [ ! -d "venv" ]; then
        echo "[*] Creating virtual environment (venv)..."
        python3 -m venv venv
    fi
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
        ./venv/Scripts/pip install --upgrade pip "poetry>=2.0.0"
        ./venv/Scripts/poetry install "${INSTALL_EXTRAS[@]}"
        RUN_CMD="./venv/Scripts/poetry run"
        PYTHON_CMD="./venv/Scripts/poetry run python"
    else
        ./venv/bin/pip install --upgrade pip "poetry>=2.0.0"
        ./venv/bin/poetry install "${INSTALL_EXTRAS[@]}"
        RUN_CMD="./venv/bin/poetry run"
        PYTHON_CMD="./venv/bin/poetry run python"
    fi
fi

echo "[*] Checking backend dependencies, including LanceDB..."
if ! $PYTHON_CMD -c "import fastapi, uvicorn, sqlalchemy, alembic, cryptography, pydantic_settings, lancedb"; then
    echo "[!] Backend dependencies are unavailable after installation. Check the Poetry installation output above."
    exit 1
fi

if [ "$CONCORDIA" = true ]; then
    $PYTHON_CMD -c "import sys; from importlib.metadata import version; assert sys.version_info >= (3, 12), 'Concordia requires Python 3.12 or 3.13'; assert version('gdm-concordia') == '2.4.0'"
fi

# 4. Security Keys
mkdir -p data

# Share dotenv parsing and safe existing-database behavior with PowerShell setup.
$PYTHON_CMD -m scripts.setup_keys

# 5. Database Setup (Migrations)
echo "[*] Running database migrations..."
$PYTHON_CMD -m alembic upgrade head

# 6. Frontend Setup
echo "[*] Installing frontend dependencies..."
if ! command -v npm &> /dev/null; then
    echo "[!] Error: 'npm' is not installed or not in PATH. Please install Node.js and npm first."
    exit 1
fi
if command -v node &> /dev/null; then
    echo "[+] Found Node.js version: $(node --version)"
fi
cd frontend
npm install --include=dev
cd ..
if [ ! -f "frontend/node_modules/.bin/vite" ]; then
    echo "[!] Error: Vite executable not found in frontend/node_modules/.bin/vite after npm install."
    exit 1
fi

# 7. Git Hooks Setup
if [ -d ".git" ]; then
    echo "[*] Configuring Git pre-commit hooks..."
    git config core.hooksPath .githooks
    echo "[+] Git hooks linked to .githooks"
fi

echo -e "\n--- Setup Complete! ---"
echo "To start the application:"
echo "Backend: $RUN_CMD python -m backend.main (or: $RUN_CMD taleweaver)"
echo "Frontend: cd frontend && npm run dev"

# 7. Start (Optional)
if [ "$SKIP_START" = false ]; then
    echo
    read -p "Would you like to start the application now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "[*] Starting backend..."
        $RUN_CMD python -m backend.main &
        BACKEND_PID=$!
        
        echo "[*] Starting frontend..."
        cd frontend && npm run dev &
        FRONTEND_PID=$!
        
        echo "Processes started. PIDs: Backend=$BACKEND_PID, Frontend=$FRONTEND_PID"
        echo "Press Ctrl+C to stop (though background processes might need manual kill if shell exits)"
        wait
    fi
fi
