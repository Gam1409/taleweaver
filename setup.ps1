# TaleWeaver Setup Script (PowerShell)
# This script sets up the Python environment, database, and frontend dependencies.

param (
    [switch]$SkipStart
)

$ErrorActionPreference = "Stop"

# Change directory to the repository root directory
$scriptPath = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if ($scriptPath) { Set-Location $scriptPath } else { $scriptPath = (Get-Location).Path }

. (Join-Path $scriptPath "scripts/powershell-environment.ps1")
Write-Host "--- TaleWeaver Setup ---" -ForegroundColor Cyan

# 1. Environment Variables (.env)
if (-not (Test-Path ".env")) {
    Write-Host "[*] Creating .env from .env.example..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
}

$envFile = Get-Content ".env" -Raw
if ($envFile -notmatch "PROJECT_NAME=") {
    $envFile = "PROJECT_NAME=`"TaleWeaver`"`r`n" + $envFile
} else {
    $envFile = $envFile -replace "PROJECT_NAME=.*", "PROJECT_NAME=`"TaleWeaver`""
}
Set-Content ".env" $envFile

# 2. Dependency Management (Poetry)
Write-Host "[*] Setting up Python dependencies with Poetry..." -ForegroundColor Yellow
$poetryExe = Get-TaleWeaverPoetry -ProjectRoot $scriptPath
if (-not $poetryExe) {
    Write-Host "[*] Poetry not found in PATH. Checking virtual environment (venv)..." -ForegroundColor Yellow
    $bootstrapPython = Get-TaleWeaverPython -ProjectRoot $scriptPath
    if (-not $bootstrapPython) {
        Write-Host "[*] Creating virtual environment (venv)..." -ForegroundColor Yellow
        Invoke-TaleWeaverNative -Command python -Arguments @("-m", "venv", "venv")
        $bootstrapPython = Get-TaleWeaverPython -ProjectRoot $scriptPath
    }
    Write-Host "[*] Installing Poetry in the local virtual environment..." -ForegroundColor Yellow
    Invoke-TaleWeaverNative -Command $bootstrapPython -Arguments @("-m", "pip", "install", "--upgrade", "pip", "poetry>=2.0.0,<3.0.0")
    $poetryExe = Get-TaleWeaverPoetry -ProjectRoot $scriptPath
}
Invoke-TaleWeaverNative -Command $poetryExe -Arguments @("install", "--no-interaction")
$pythonExe = Get-TaleWeaverPython -ProjectRoot $scriptPath
if (-not (Test-TaleWeaverBackend -Python $pythonExe)) {
    throw "Backend dependencies are unavailable after installation. Check the Poetry installation output above."
}
Write-Host "[+] Backend Python: $pythonExe" -ForegroundColor Green

# 4. Security Keys
if (-not (Test-Path "data")) {
    Write-Host "[*] Creating data directory..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path "data" | Out-Null
}

# Helper: set or append a key=value pair in .env
# If the key line already exists it is replaced, otherwise appended.
function Set-EnvKey {
    param([string]$Key, [string]$Value)
    $content = Get-Content ".env" -Raw
    if ($content -match "(?m)^${Key}=") {
        $content = $content -replace "(?m)^${Key}=.*", "${Key}=${Value}"
    } else {
        $content = $content.TrimEnd() + "`r`n${Key}=${Value}`r`n"
    }
    Set-Content ".env" $content -NoNewline
}

$envFile = Get-Content ".env" -Raw

# ENCRYPTION_KEY
if ($envFile -notmatch "(?m)^ENCRYPTION_KEY=[a-zA-Z0-9+/=_-]{20,}") {
    Write-Host "[*] Generating ENCRYPTION_KEY..." -ForegroundColor Yellow
    $key = Invoke-TaleWeaverNative -Command $pythonExe -Arguments @("-c", "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    Set-EnvKey "ENCRYPTION_KEY" $key
    Write-Host "[+] ENCRYPTION_KEY written to .env" -ForegroundColor Green
}

# SECRET_KEY
$envFile = Get-Content ".env" -Raw
if ($envFile -notmatch "(?m)^SECRET_KEY=[a-fA-F0-9]{64}") {
    Write-Host "[*] Generating SECRET_KEY..." -ForegroundColor Yellow
    $skey = Invoke-TaleWeaverNative -Command $pythonExe -Arguments @("-c", "import secrets; print(secrets.token_hex(32))")
    Set-EnvKey "SECRET_KEY" $skey
    Write-Host "[+] SECRET_KEY written to .env" -ForegroundColor Green
}


# 5. Database Setup (Migrations)
Write-Host "[*] Running database migrations..." -ForegroundColor Yellow
Invoke-TaleWeaverNative -Command $pythonExe -Arguments @("-m", "alembic", "upgrade", "head")

# 6. Frontend Setup
Write-Host "[*] Installing frontend dependencies..." -ForegroundColor Yellow
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is not installed or not in PATH. Please install Node.js and npm first."
}
if (Get-Command node -ErrorAction SilentlyContinue) {
    $nodeVersion = Invoke-TaleWeaverNative -Command node -Arguments @("--version")
    Write-Host "[+] Found Node.js version: $nodeVersion" -ForegroundColor Green
}
Push-Location frontend
try {
    Invoke-TaleWeaverNative -Command npm -Arguments @("install", "--include=dev")
    if (-not ((Test-Path "node_modules/.bin/vite.cmd") -or (Test-Path "node_modules/.bin/vite"))) {
        throw "Vite executable not found in frontend/node_modules/.bin after npm install."
    }
} finally {
    Pop-Location
}

# 7. Git Hooks Setup
if (Test-Path ".git") {
    Write-Host "[*] Configuring Git pre-commit hooks..." -ForegroundColor Yellow
    Invoke-TaleWeaverNative -Command git -Arguments @("config", "core.hooksPath", ".githooks")
    Write-Host "[+] Git hooks linked to .githooks" -ForegroundColor Green
}

Write-Host "`n--- Setup Complete! ---" -ForegroundColor Green
Write-Host "To start the application:"
Write-Host "Run .\run.ps1 to start both services with the installed Python environment."
Write-Host ("Backend only: & '{0}' -m backend.main" -f $pythonExe.Replace("'", "''"))
Write-Host "Frontend: cd frontend; npm run dev`n"

# 7. Start (Optional / Interactive)
if (-not $SkipStart) {
    $start = Read-Host "Would you like to start the application now? (y/n)"
    if ($start -eq "y") {
        Write-Host "[*] Starting backend and frontend in new windows..." -ForegroundColor Cyan
        Start-TaleWeaverProcesses -ProjectRoot $scriptPath -Python $pythonExe
    }
}
