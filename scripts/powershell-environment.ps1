# Shared environment resolution for setup.ps1 and run.ps1.

function Get-TaleWeaverPoetry {
    param([string]$ProjectRoot)

    $command = Get-Command poetry -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($relative in @("venv/Scripts/poetry.exe", ".venv/Scripts/poetry.exe", "venv/bin/poetry", ".venv/bin/poetry")) {
        $candidate = Join-Path $ProjectRoot $relative
        if (Test-Path $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}

function Invoke-TaleWeaverNative {
    param([string]$Command, [string[]]$Arguments)

    $global:LASTEXITCODE = $null
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command '$Command' failed (exit code $LASTEXITCODE). Setup cannot continue."
    }
}

function Get-TaleWeaverPython {
    param([string]$ProjectRoot)

    $poetry = Get-TaleWeaverPoetry -ProjectRoot $ProjectRoot
    if ($poetry) {
        Push-Location $ProjectRoot
        try {
            # Poetry may use .venv or its central cache, independently of venv/.
            $resolved = @(& $poetry env info --executable 2>$null)
            if ($LASTEXITCODE -eq 0 -and $resolved.Count -gt 0) {
                $candidate = ([string]$resolved[-1]).Trim()
                if (Test-Path $candidate -PathType Leaf) { return $candidate }
            }
        } catch {
            # No Poetry environment yet; allow an existing local installation.
            Write-Verbose "Poetry environment lookup failed; checking local virtual environments."
        } finally {
            Pop-Location
        }
    }
    foreach ($relative in @(".venv/Scripts/python.exe", ".venv/bin/python", "venv/Scripts/python.exe", "venv/bin/python")) {
        $candidate = Join-Path $ProjectRoot $relative
        if (Test-Path $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}

function Test-TaleWeaverBackend {
    param([string]$Python)

    if (-not $Python) { return $false }
    try {
        $global:LASTEXITCODE = $null
        & $Python -c "import fastapi, uvicorn, sqlalchemy, alembic, cryptography, pydantic_settings, lancedb" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Start-TaleWeaverProcesses {
    param([string]$ProjectRoot, [string]$Python)

    $frontendRoot = Join-Path $ProjectRoot "frontend"
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        $shell = (Get-Process -Id $PID).Path
        $backendCommand = "& '{0}' -m backend.main" -f $Python.Replace("'", "''")
        # EncodedCommand keeps spaces and apostrophes in checkout paths intact.
        $backendEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($backendCommand))
        $frontendEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes("npm run dev"))
        Start-Process -FilePath $shell -WorkingDirectory $ProjectRoot -ArgumentList @("-NoExit", "-EncodedCommand", $backendEncoded)
        Start-Process -FilePath $shell -WorkingDirectory $frontendRoot -ArgumentList @("-NoExit", "-EncodedCommand", $frontendEncoded)
        return
    }
    Start-Job -ArgumentList $ProjectRoot, $Python -ScriptBlock {
        param($Root, $Interpreter)
        Set-Location $Root
        & $Interpreter -m backend.main
    }
    Start-Job -ArgumentList $frontendRoot -ScriptBlock {
        param($Root)
        Set-Location $Root
        npm run dev
    }
}
