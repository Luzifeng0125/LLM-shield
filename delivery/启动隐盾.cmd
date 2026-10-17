@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
if not exist "%~dp0runtime\training_env\Scripts\python.exe" (
  echo Current Python environment missing: runtime\training_env
  exit /b 1
)
"%~dp0runtime\training_env\Scripts\python.exe" -B -X utf8 "%~dp0app\scripts\start_reviewed_candidate.py" --action-model "%~dp0app\models\necessity_action.joblib" --ner-decoding bio_viterbi --port 8789 %*
exit /b %errorlevel%
