@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "..\..\delivery\运行Python.cmd" (
  call "..\..\delivery\运行Python.cmd" -B -X utf8 scripts/validate_dataset.py
) else (
  python -B -X utf8 scripts/validate_dataset.py
)
if errorlevel 1 echo Validation failed. See the output above.
pause
