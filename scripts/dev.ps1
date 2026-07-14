$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m venv apps/api/.venv
& apps/api/.venv/Scripts/pip.exe install -e "apps/api[dev]"
Push-Location apps/api; & .venv/Scripts/alembic.exe upgrade head; Pop-Location
& apps/api/.venv/Scripts/python.exe scripts/seed_demo.py
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root/apps/api'; .venv/Scripts/uvicorn.exe app.main:app --reload --host 0.0.0.0 --port 8000"
Set-Location apps/web
npm install
npm run dev -- --host 0.0.0.0

