# TaleWeaver Run Script (PowerShell)
# This script pulls the latest Git changes, checks setup status, offers to setup if incomplete, and runs the app.

$ErrorActionPreference = "Stop"

# Change directory to the repository root directory
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($scriptPath) {
    Set-Location $scriptPath
}
. (Join-Path $PSScriptRoot "scripts/powershell-environment.ps1")

Write-Host "==============================" -ForegroundColor Green
Write-Host "      TaleWeaver Runner       " -ForegroundColor Green
Write-Host "==============================" -ForegroundColor Green

# 1. Fetch current stand from Git
if (Test-Path ".git") {
    Write-Host "[*] Fetching latest changes from Git..." -ForegroundColor Cyan
    try {
        git pull
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[!] Warning: Git pull failed. Continuing with local files..." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[!] Warning: Git pull failed. Continuing anyway..." -ForegroundColor Yellow
    }
} else {
    Write-Host "[!] Not a Git repository, skipping Git pull." -ForegroundColor Yellow
}

# 2. Check setup status
$setupNeeded = $false
$pythonExe = Get-TaleWeaverPython -ProjectRoot $PSScriptRoot
if (-not (Test-Path ".env")) { $setupNeeded = $true }
if (-not (Test-TaleWeaverBackend -Python $pythonExe)) { $setupNeeded = $true }
if (-not (Test-Path "frontend/node_modules")) { $setupNeeded = $true }

if ($setupNeeded) {
    Write-Host "[!] Project setup is incomplete (.env, Python dependencies, or node_modules missing)." -ForegroundColor Yellow
    $choice = Read-Host "Would you like to run the setup script now? (y/n)"
    if ($choice -eq "y" -or $choice -eq "Y") {
        Write-Host "[*] Running setup.ps1..." -ForegroundColor Cyan
        & .\setup.ps1 -SkipStart
        # Re-check after setup runs
        $pythonExe = Get-TaleWeaverPython -ProjectRoot $PSScriptRoot
        if (-not (Test-Path ".env") -or -not (Test-TaleWeaverBackend -Python $pythonExe) -or -not (Test-Path "frontend/node_modules")) {
            Write-Host "[!] Setup failed or is still incomplete. Exiting." -ForegroundColor Red
            Exit 1
        }
    } else {
        Write-Host "[*] Run .\setup.ps1 -SkipStart to install dependencies, then .\run.ps1."
        Exit 1
    }
}

# 3. Start the application locally
Write-Host "[*] Starting backend and frontend..." -ForegroundColor Green
Write-Host "[*] Backend Python: $pythonExe" -ForegroundColor Cyan
Start-TaleWeaverProcesses -ProjectRoot $PSScriptRoot -Python $pythonExe
