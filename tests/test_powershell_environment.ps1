# Run with: pwsh -NoProfile -File tests/test_powershell_environment.ps1
param([string]$Python)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
. (Join-Path $repo "scripts/powershell-environment.ps1")
if (-not $Python) { $Python = Get-TaleWeaverPython -ProjectRoot $repo }
if (-not (Test-TaleWeaverBackend -Python $Python)) {
    throw "These tests require an installed backend Python environment."
}

function Assert-Equal {
    param($Actual, $Expected, [string]$Label)
    if ($Actual -ne $Expected) { throw "$Label`: expected '$Expected', got '$Actual'." }
    Write-Host "PASS: $Label"
}

$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("TaleWeaver user's test " + [guid]::NewGuid())
$originalPath = $env:PATH
$originalLocation = Get-Location
New-Item -ItemType Directory -Path $testRoot | Out-Null
try {
    # Directory existence alone must not count as a usable installation.
    $env:PATH = $testRoot
    $legacyPython = Join-Path $testRoot "venv/Scripts/python.exe"
    New-Item -ItemType Directory -Path (Split-Path $legacyPython) -Force | Out-Null
    Assert-Equal (Get-TaleWeaverPython $testRoot) $null "Empty venv is not an interpreter"
    Set-Content $legacyPython "not an executable"
    Assert-Equal (Get-TaleWeaverPython $testRoot) $legacyPython "Legacy venv resolution"
    Assert-Equal (Test-TaleWeaverBackend $legacyPython) $false "Broken interpreter is rejected"

    $localPython = Join-Path $testRoot ".venv/Scripts/python.exe"
    New-Item -ItemType Directory -Path (Split-Path $localPython) -Force | Out-Null
    Set-Content $localPython "not an executable"
    Assert-Equal (Get-TaleWeaverPython $testRoot) $localPython "Project .venv takes precedence over stale venv"
    $localPoetry = Join-Path $testRoot "venv/Scripts/poetry.exe"
    Set-Content $localPoetry "placeholder"
    Assert-Equal (Get-TaleWeaverPoetry $testRoot) $localPoetry "Locally bootstrapped Poetry discovery"
    Remove-Item $localPoetry
    $env:PATH = $originalPath

    $script:PoetryForTest = Join-Path $testRoot "poetry-stub.ps1"
    $pythonLiteral = $Python.Replace("'", "''")
    Set-Content $script:PoetryForTest "if ((`$args -join ' ') -ne 'env info --executable') { exit 9 }; Write-Output '$pythonLiteral'; exit 0"
    function Get-TaleWeaverPoetry { param([string]$ProjectRoot); return $script:PoetryForTest }
    Assert-Equal (Get-TaleWeaverPython $testRoot) $Python "Poetry environment wins over both stale local directories"
    Assert-Equal (Get-Location).Path $originalLocation.Path "Environment lookup restores working directory"
    Set-Content $script:PoetryForTest "exit 1"
    Assert-Equal (Get-TaleWeaverPython $testRoot) $localPython "Absent Poetry environment permits local fallback"

    $failed = $false
    try { Invoke-TaleWeaverNative $Python @("-c", "raise SystemExit(17)") } catch { $failed = $true }
    Assert-Equal $failed $true "Native dependency-command failure stops setup"
    $result = Invoke-TaleWeaverNative $Python @("-c", "print('ok')")
    Assert-Equal $result "ok" "Successful native output remains available for key generation"

    # Exercise the actual runner without opening windows, running setup, or using the network.
    Copy-Item (Join-Path $repo "run.ps1") $testRoot
    New-Item -ItemType Directory -Path (Join-Path $testRoot "scripts"), (Join-Path $testRoot "frontend/node_modules/.bin") -Force | Out-Null
    Set-Content (Join-Path $testRoot "frontend/node_modules/.bin/vite") "placeholder"
    Set-Content (Join-Path $testRoot ".env") "PROJECT_NAME=TaleWeaver"
    $helper = Join-Path $testRoot "scripts/powershell-environment.ps1"
    Copy-Item (Join-Path $repo "scripts/powershell-environment.ps1") $helper
    $stubLiteral = $script:PoetryForTest.Replace("'", "''")
    Add-Content $helper @"
function Get-TaleWeaverPoetry { param([string]`$ProjectRoot); return '$stubLiteral' }
function Start-TaleWeaverProcesses {
    param([string]`$ProjectRoot, [string]`$Python)
    @{ Root = `$ProjectRoot; Python = `$Python } | ConvertTo-Json | Set-Content (Join-Path `$ProjectRoot 'launch.json')
}
function Read-Host { throw 'A ready Poetry installation must not trigger setup prompts.' }
"@
    Set-Content $script:PoetryForTest "Write-Output '$pythonLiteral'; exit 0"
    $shellExe = (Get-Process -Id $PID).Path
    Invoke-TaleWeaverNative $shellExe @("-NoProfile", "-File", (Join-Path $testRoot "run.ps1"))
    $launch = Get-Content (Join-Path $testRoot "launch.json") -Raw | ConvertFrom-Json
    Assert-Equal $launch.Python $Python "Runner launches the Poetry interpreter with FastAPI installed"
    Assert-Equal $launch.Root $testRoot "Runner handles a checkout path containing spaces and an apostrophe"

    Remove-Item (Join-Path $testRoot "frontend/node_modules/.bin/vite")
    Remove-Item (Join-Path $testRoot "launch.json")
    & $shellExe -NoProfile -File (Join-Path $testRoot "run.ps1") *> $null
    Assert-Equal ($LASTEXITCODE -ne 0) $true "Missing Vite triggers the runner's setup check"
    Assert-Equal (Test-Path (Join-Path $testRoot "launch.json")) $false "Runner does not launch without Vite"

    # A failed install must not reach key generation, migrations, or frontend setup.
    Copy-Item (Join-Path $repo "setup.ps1") $testRoot
    Set-Content $script:PoetryForTest "exit 17"
    & $shellExe -NoProfile -File (Join-Path $testRoot "setup.ps1") -SkipStart *> $null
    Assert-Equal ($LASTEXITCODE -ne 0) $true "Setup returns failure when Poetry install fails"
    Assert-Equal (Test-Path (Join-Path $testRoot "data")) $false "Failed install stops before data initialization"

    $brokenLiteral = $localPython.Replace("'", "''")
    Set-Content $script:PoetryForTest "if (`$args[0] -eq 'env') { Write-Output '$brokenLiteral' }; exit 0"
    & $shellExe -NoProfile -File (Join-Path $testRoot "setup.ps1") -SkipStart *> $null
    Assert-Equal ($LASTEXITCODE -ne 0) $true "Setup rejects a successful installer with missing dependencies"
    Assert-Equal (Test-Path (Join-Path $testRoot "data")) $false "Missing dependencies stop before migrations"

    # Exercise frontend installation without installing packages or running migrations.
    Set-Content $script:PoetryForTest "Write-Output '$pythonLiteral'; exit 0"
    Add-Content $helper @'
function Invoke-TaleWeaverNative {
    param([string]$Command, [string[]]$Arguments)
    if ($Command -eq 'node') { return 'v24.0.0' }
    if ($Command -ne 'npm') { return }
    $Arguments -join ' ' | Set-Content (Join-Path $PSScriptRoot '../npm-arguments.txt')
    if (Test-Path (Join-Path $PSScriptRoot '../install-vite')) {
        Set-Content 'node_modules/.bin/vite' 'placeholder'
    }
}
'@
    Set-Content (Join-Path $testRoot ".env") ("PROJECT_NAME=TaleWeaver`nENCRYPTION_KEY=" + ('a' * 44) + "`nSECRET_KEY=" + ('b' * 64))
    & $shellExe -NoProfile -File (Join-Path $testRoot "setup.ps1") -SkipStart *> $null
    Assert-Equal ($LASTEXITCODE -ne 0) $true "Setup rejects npm success without a Vite binary"
    Assert-Equal (Get-Content (Join-Path $testRoot "npm-arguments.txt")) "install --include=dev" "Setup explicitly installs frontend development dependencies"
    Set-Content (Join-Path $testRoot "install-vite") "enabled"
    & $shellExe -NoProfile -File (Join-Path $testRoot "setup.ps1") -SkipStart *> $null
    Assert-Equal $LASTEXITCODE 0 "Setup succeeds with Poetry dependencies and Vite available"
    Assert-Equal (Test-Path (Join-Path $testRoot "launch.json")) $false "SkipStart does not launch application processes"
} finally {
    $env:PATH = $originalPath
    Set-Location $originalLocation
    Remove-Item -Recurse -Force $testRoot
}
