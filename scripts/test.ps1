$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TestRoot = Join-Path ([IO.Path]::GetTempPath()) ("ai-job-coach-tests-" + [guid]::NewGuid().ToString("N"))
$TestRoot = [IO.Path]::GetFullPath($TestRoot)
$StoragePath = Join-Path $TestRoot "uploads"
New-Item -ItemType Directory -Path $StoragePath -Force | Out-Null

$TestEnvironment = @{
    AI_JOB_COACH_TEST_ROOT = $TestRoot
    APP_ENV = "test"
    DATABASE_URL = "sqlite:///$($TestRoot.Replace('\', '/'))/app.db"
    LOCAL_STORAGE_PATH = $StoragePath
    STORAGE_PROVIDER = "local"
    LLM_PROVIDER = "mock"
    LLM_API_BASE_URL = ""
    LLM_API_KEY = ""
    LLM_MODEL = ""
    LLM_MODEL_CHEAP = ""
    LLM_MODEL_STRONG = ""
    PAYMENT_PROVIDER = "disabled"
    JOB_SOURCE_ALLOWED_HOSTS = ""
    DEMO_ADMIN_EMAIL = "admin@example.test"
    DEMO_ADMIN_PASSWORD = "ChangeMe123!"
    DEMO_ADVISOR_EMAIL = "advisor@example.test"
    DEMO_ADVISOR_PASSWORD = "ChangeMe123!"
    DEMO_USER_EMAIL = "user@example.test"
    DEMO_USER_PASSWORD = "ChangeMe123!"
}
$PreviousEnvironment = @{}
foreach ($Name in $TestEnvironment.Keys) {
    $PreviousEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
    [Environment]::SetEnvironmentVariable($Name, $TestEnvironment[$Name], "Process")
}

try {
    Push-Location "$Root/apps/api"
    try {
        & .venv/Scripts/python.exe -m pytest
    }
    finally {
        Pop-Location
    }

    Push-Location "$Root/apps/web"
    try {
        npm test -- --run
        npm run e2e
    }
    finally {
        Pop-Location
    }
}
finally {
    foreach ($Name in $TestEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($Name, $PreviousEnvironment[$Name], "Process")
    }
    $TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($TestRoot.StartsWith($TempRoot) -and (Split-Path $TestRoot -Leaf).StartsWith("ai-job-coach-tests-")) {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
