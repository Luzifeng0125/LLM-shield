@echo off
setlocal
if defined SHIELD_PYTHON goto configured
if exist "%~dp0runtime\python-path.txt" set /p "SHIELD_PYTHON="<"%~dp0runtime\python-path.txt"
if defined SHIELD_PYTHON goto configured
if exist "%~dp0app\.venv\Scripts\python.exe" set "SHIELD_PYTHON=%~dp0app\.venv\Scripts\python.exe"
if defined SHIELD_PYTHON goto configured
echo Python environment missing. Run the setup PowerShell script in this folder first.
exit /b 1
:configured
if not exist "%SHIELD_PYTHON%" (
  echo Configured Python does not exist. Update delivery\runtime\python-path.txt.
  exit /b 1
)
"%SHIELD_PYTHON%" -B %*
exit /b %errorlevel%
