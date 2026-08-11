$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PreviousLlmProvider = $env:LLM_PROVIDER
$env:LLM_PROVIDER = "mock"
try {
    Push-Location "$Root/apps/api"; & .venv/Scripts/python.exe -m pytest; Pop-Location
    Push-Location "$Root/apps/web"; npm test -- --run; npm run e2e; Pop-Location
}
finally {
    if ($null -eq $PreviousLlmProvider) {
        Remove-Item Env:LLM_PROVIDER -ErrorAction SilentlyContinue
    }
    else {
        $env:LLM_PROVIDER = $PreviousLlmProvider
    }
}
