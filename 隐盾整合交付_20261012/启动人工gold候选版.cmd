@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
if not exist "%~dp0runtime\training_env\Scripts\python.exe" (
  echo Candidate Python environment missing: runtime\training_env
  echo The reviewed-gold candidate cannot start.
  exit /b 1
)
"%~dp0runtime\training_env\Scripts\python.exe" -X utf8 "%~dp0app\scripts\start_reviewed_candidate.py" %*
exit /b %errorlevel%
