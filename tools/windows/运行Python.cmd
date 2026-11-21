@echo off
setlocal
set "PYTHONUTF8=1"
if defined SHIELD_PYTHON goto configured
if exist "%~dp0..\..\local\runtime\delivery\python-path.txt" set /p "SHIELD_PYTHON="<"%~dp0..\..\local\runtime\delivery\python-path.txt"
if defined SHIELD_PYTHON goto configured
if exist "%~dp0..\..\app\.venv\Scripts\python.exe" set "SHIELD_PYTHON=%~dp0..\..\app\.venv\Scripts\python.exe"
if defined SHIELD_PYTHON goto configured
echo Python missing. Run tools/windows setup first.
exit /b 1
:configured
if not exist "%SHIELD_PYTHON%" exit /b 1
"%SHIELD_PYTHON%" -B %*
exit /b %errorlevel%
