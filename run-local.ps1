# Start TaleWeaver from the current checkout without checking GitHub for updates.
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "run.ps1") -NoUpdate
exit $LASTEXITCODE
