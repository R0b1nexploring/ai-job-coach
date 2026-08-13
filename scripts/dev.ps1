$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ApiBind = if ($env:DEV_API_HOST) { $env:DEV_API_HOST } else { "127.0.0.1" }
$WebBind = if ($env:DEV_WEB_HOST) { $env:DEV_WEB_HOST } else { "127.0.0.1" }
Set-Location $Root
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
New-Item -ItemType Directory -Path var/uploads -Force | Out-Null
$PrivateFiles = @(".env", "var/app.db")
foreach ($PrivateFile in $PrivateFiles) {
    if (Test-Path $PrivateFile) {
        $Acl = Get-Acl $PrivateFile
        $Acl.SetAccessRuleProtection($true, $false)
        $Acl.Access | ForEach-Object { $Acl.RemoveAccessRule($_) | Out-Null }
        $Rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
            "FullControl",
            "Allow"
        )
        $Acl.SetAccessRule($Rule)
        Set-Acl -Path $PrivateFile -AclObject $Acl
    }
}
python -m venv apps/api/.venv
& apps/api/.venv/Scripts/python.exe -m pip install -e "apps/api[dev]"
Push-Location apps/api; & .venv/Scripts/python.exe -m alembic upgrade head; Pop-Location
& apps/api/.venv/Scripts/python.exe scripts/seed_demo.py
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root/apps/api'; .venv/Scripts/python.exe -m uvicorn app.main:app --reload --host '$ApiBind' --port 8000"
Set-Location apps/web
npm install
npm run dev -- --host $WebBind
