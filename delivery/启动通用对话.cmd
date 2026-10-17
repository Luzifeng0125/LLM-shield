@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "LLM_MODE=real"
set "SHIELD_REVIEWED_NER_MODEL_DIR="
set "SHIELD_USE_GLINER=false"
set "SHIELD_USE_CAMPUS_NER=false"
call "%~dp0运行Python.cmd" -X utf8 "%~dp0app\run.py" --port 8787 %*
exit /b %errorlevel%
