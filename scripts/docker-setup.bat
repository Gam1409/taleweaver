@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."

REM TaleWeaver Docker Setup Script
REM This script builds and starts the TaleWeaver container with Nginx Reverse Proxy.

echo --- TaleWeaver Docker Setup ---

IF NOT EXIST .env (
    echo [!] .env file not found. Creating from .env.example...
    copy .env.example .env
    echo [i] Please edit the .env file and set your ENCRYPTION_KEY and API keys.
)

REM Read HTTPS_PORT and DOCKER_DATA_DIR from .env
for /f "tokens=1,2 delims==" %%a in (.env) do (
    if "%%a"=="HTTPS_PORT" set HTTPS_PORT=%%b
    if "%%a"=="DOCKER_DATA_DIR" set DOCKER_DATA_DIR=%%b
)
IF "%HTTPS_PORT%"=="" set HTTPS_PORT=443
IF "%DOCKER_DATA_DIR%"=="" set DOCKER_DATA_DIR=./data-docker

IF NOT EXIST "%DOCKER_DATA_DIR%" (
    echo [*] Creating isolated data directory at %DOCKER_DATA_DIR%...
    mkdir "%DOCKER_DATA_DIR%"
)

IF NOT EXIST nginx (
    mkdir nginx
)

IF EXIST nginx\nginx.conf\ (
    echo [!] nginx\nginx.conf is a directory. Restore the canonical file before deploying.
    exit /b 1
)
IF NOT EXIST nginx\nginx.conf (
    echo [!] Missing nginx\nginx.conf. Restore it from this checkout before deploying.
    exit /b 1
)

IF NOT EXIST nginx\ssl (
    mkdir nginx\ssl
)

IF NOT EXIST nginx\ssl\nginx.crt (
    echo [*] Generating self-signed SSL certificate...
    docker run --rm -v "%cd%\nginx\ssl:/export" alpine sh -c "apk add --no-cache openssl && openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /export/nginx.key -out /export/nginx.crt -subj '/CN=localhost'"
)

echo [*] Building and starting container...
docker compose up -d --build

if %ERRORLEVEL% NEQ 0 (
    echo [!] Docker build failed. Please check the error messages above.
    exit /b %ERRORLEVEL%
)

echo --------------------------------
echo [+] TaleWeaver is now running with HTTPS!
echo [+] Access the UI at: https://localhost:%HTTPS_PORT%
echo [+] (Example adventures are being imported automatically)
echo [+] Logs: docker compose logs -f
echo --------------------------------
pause
