param(
    [string]$PythonPath = "",
    [switch]$WithNer
)

$ErrorActionPreference = "Stop"
$appDir = Join-Path $PSScriptRoot "app"
$venvPython = Join-Path $appDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($PythonPath) {
        if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
            throw "PythonPath does not exist: $PythonPath"
        }
        $basePython = (Resolve-Path -LiteralPath $PythonPath).Path
    } else {
        $basePython = $null
        if (Get-Command py -ErrorAction SilentlyContinue) {
            foreach ($line in (& py -0p 2>$null)) {
                if ($line -match '3\.12' -and $line -match '(?<exe>[A-Za-z]:\\.+python\.exe)\s*$') {
                    $basePython = $Matches.exe
                    break
                }
            }
        }
        if (-not $basePython -and (Get-Command python -ErrorAction SilentlyContinue)) {
            $candidate = (Get-Command python).Source
            if ((& $candidate -c 'import sys; print(sys.version_info[:2] == (3, 12))') -eq 'True') {
                $basePython = $candidate
            }
        }
        if (-not $basePython) {
            throw "Python 3.12 not found. Install it or pass -PythonPath C:\path\to\python.exe"
        }
    }
    if ((& $basePython -c 'import sys; print(sys.version_info[:2] == (3, 12))') -ne 'True') {
        throw "The selected Python must be version 3.12."
    }
    & $basePython -m venv (Join-Path $appDir ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
}

& $venvPython -m pip install -r (Join-Path $appDir "requirements-lock.txt")
if ($LASTEXITCODE -ne 0) { throw "Base dependency installation failed." }
if ($WithNer) {
    & $venvPython -m pip install -r (Join-Path $appDir "requirements-reviewed-inference.txt")
    if ($LASTEXITCODE -ne 0) { throw "NER inference dependency installation failed." }
}

Write-Host "Python environment ready: $venvPython"
Write-Host "The reviewed_ner model is not in Git. See the GitHub installation guide under docs before starting the maintained profile."
