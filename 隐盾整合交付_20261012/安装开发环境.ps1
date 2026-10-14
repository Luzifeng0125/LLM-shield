$ErrorActionPreference = 'Stop'
$appRoot = Join-Path $PSScriptRoot 'app'
$venvPython = Join-Path $appRoot '.venv\Scripts\python.exe'
function Assert-Success([string]$message) {
    if ($LASTEXITCODE -ne 0) { throw $message }
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv (Join-Path $appRoot '.venv')
        Assert-Success 'Python 3.12 is required. Install it and run this script again.'
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)'
        Assert-Success 'Python 3.12 is required for the pinned model dependencies.'
        & python -m venv (Join-Path $appRoot '.venv')
        Assert-Success 'Could not create the project virtual environment.'
    } else {
        throw 'Install Python 3.12, then run this script again.'
    }
}
& $venvPython -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)'
Assert-Success 'The existing virtual environment must use Python 3.12.'
& $venvPython -m pip install -r (Join-Path $appRoot 'requirements-lock.txt')
Assert-Success 'Dependency installation failed; no existing configuration was replaced.'
$localConfig = Join-Path $appRoot '.env'
if (-not (Test-Path -LiteralPath $localConfig)) {
    Copy-Item -LiteralPath (Join-Path $appRoot '.env.example') -Destination $localConfig
}
Write-Output 'Setup complete. Start the application using the launcher in this folder.'
