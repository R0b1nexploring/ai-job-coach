$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location "$Root/apps/api"; & .venv/Scripts/pytest.exe; Pop-Location
Push-Location "$Root/apps/web"; npm test -- --run; npm run e2e; Pop-Location

