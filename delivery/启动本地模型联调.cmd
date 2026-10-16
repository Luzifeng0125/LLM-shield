@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
if not exist "%~dp0runtime\training_env\Scripts\python.exe" (
  echo Candidate Python environment missing: runtime\training_env
  exit /b 1
)
"%~dp0runtime\training_env\Scripts\python.exe" -X utf8 "%~dp0app\scripts\start_reviewed_candidate.py" --action-model "%~dp0app\outputs\local_model_debug_20261016\segment_coverage_v2\segment_action.joblib" --ner-decoding bio_viterbi --port 8789 %*
exit /b %errorlevel%
