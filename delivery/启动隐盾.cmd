@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
if exist "%~dp0runtime\training_env\Scripts\python.exe" (
  set "SHIELD_PYTHON=%~dp0runtime\training_env\Scripts\python.exe"
) else if exist "%~dp0app\.venv\Scripts\python.exe" (
  set "SHIELD_PYTHON=%~dp0app\.venv\Scripts\python.exe"
) else (
  echo Python environment missing. Run delivery\安装开发环境.ps1 first.
  exit /b 1
)
"%SHIELD_PYTHON%" -B -X utf8 "%~dp0app\scripts\start_reviewed_candidate.py" --action-model "%~dp0app\models\necessity_action.joblib" --ner-decoding bio_viterbi --port 8789 %*
exit /b %errorlevel%
