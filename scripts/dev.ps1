$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ApiBind = if ($env:DEV_API_HOST) { $env:DEV_API_HOST } else { "127.0.0.1" }
$WebBind = if ($env:DEV_WEB_HOST) { $env:DEV_WEB_HOST } else { "127.0.0.1" }
Set-Location $Root
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
$EnvApiPort = ""
if (Test-Path .env) {
    $EnvApiPort = ((Get-Content .env | Where-Object { $_ -match '^API_PORT=' } | Select-Object -First 1) -replace '^API_PORT=', '').Trim()
}
$ApiPort = if ($env:API_PORT) { $env:API_PORT } elseif ($EnvApiPort) { $EnvApiPort } else { "8000" }
if ($ApiPort -notmatch '^[0-9]+$' -or [int]$ApiPort -lt 1 -or [int]$ApiPort -gt 65535) {
    throw "错误：API_PORT 必须是 1-65535 的端口号，当前为 '$ApiPort'。"
}
$ApiPortInUse = Get-NetTCPConnection -LocalPort ([int]$ApiPort) -State Listen -ErrorAction SilentlyContinue
if ($ApiPortInUse) {
    throw "错误：API 端口 $ApiPort 已被占用。请停止占用进程，或设置 API_PORT 为其他端口。"
}
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
$WorkerProcess = Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root/apps/api'; .venv/Scripts/python.exe -m app.worker" -PassThru
$ApiProcess = Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root/apps/api'; .venv/Scripts/python.exe -m uvicorn app.main:app --reload --host '$ApiBind' --port $ApiPort" -PassThru
$ApiReady = $false
for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
    if ($ApiProcess.HasExited) {
        throw "错误：API 进程启动失败，请检查 API 窗口中的 uvicorn 日志。"
    }
    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/api/health" -TimeoutSec 2
        if ($Health.status -eq "ok") {
            $ApiReady = $true
            break
        }
    }
    catch { }
    Start-Sleep -Seconds 1
}
if (-not $ApiReady) {
    throw "错误：API 在 30 秒内未就绪，请访问 http://127.0.0.1:$ApiPort/api/health 检查。"
}
Set-Location apps/web
$env:API_PORT = $ApiPort
try {
    npm install
    npm run dev -- --host $WebBind
}
finally {
    if ($ApiProcess -and -not $ApiProcess.HasExited) { Stop-Process -Id $ApiProcess.Id -Force -ErrorAction SilentlyContinue }
    if ($WorkerProcess -and -not $WorkerProcess.HasExited) { Stop-Process -Id $WorkerProcess.Id -Force -ErrorAction SilentlyContinue }
}
