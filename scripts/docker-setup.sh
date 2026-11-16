#!/bin/bash

# TaleWeaver Docker Setup Script
# This script builds and starts the TaleWeaver container with Nginx Reverse Proxy.

# Navigate to project root
cd "$(dirname "$0")/.."

echo "--- TaleWeaver Docker Setup ---"

# Check for .env file
if [ ! -f .env ]; then
    echo "[!] .env file not found. Creating from .env.example..."
    cp .env.example .env
    echo "[i] Please edit the .env file and set your ENCRYPTION_KEY and API keys."
fi

# Read HTTPS_PORT and DOCKER_DATA_DIR from .env
HTTPS_PORT=$(grep HTTPS_PORT .env | cut -d '=' -f2 | tr -d '\r')
HTTPS_PORT=${HTTPS_PORT:-443}

DOCKER_DATA_DIR=$(grep DOCKER_DATA_DIR .env | cut -d '=' -f2 | tr -d '\r')
DOCKER_DATA_DIR=${DOCKER_DATA_DIR:-./data-docker}

# Create data directory if it doesn't exist
mkdir -p "$DOCKER_DATA_DIR"

# Ensure nginx directories exist
mkdir -p nginx/ssl

# Use the reviewed configuration only. Never delete a mount directory or invent
# a weaker proxy policy when the checkout is incomplete.
if [ ! -f nginx/nginx.conf ]; then
    echo "[!] Missing nginx/nginx.conf. Restore it from this checkout before deploying." >&2
    exit 1
fi

# Generate SSL certificate if it doesn't exist
if [ ! -f nginx/ssl/nginx.crt ]; then
    echo "[*] Generating self-signed SSL certificate..."
    docker run --rm -v "$(pwd)/nginx/ssl:/export" alpine sh -c "apk add --no-cache openssl && openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /export/nginx.key -out /export/nginx.crt -subj '/CN=localhost'"
fi

# Build and start
echo "[*] Building and starting container..."
docker compose up -d --build

if [ $? -ne 0 ]; then
    echo "[!] Docker build failed. Please check the error messages above."
    exit 1
fi

echo "--------------------------------"
echo "[+] TaleWeaver is now running with HTTPS!"
echo "[+] Access the UI at: https://localhost:$HTTPS_PORT"
echo "[+] (Example adventures are being imported automatically)"
echo "[+] Logs: docker compose logs -f"
echo "--------------------------------"
