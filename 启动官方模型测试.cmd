@echo off
setlocal
chcp 65001 >nul
set "SHIELD_GLINER_MODEL_DIR=%~dp0app\models\gliner_official_multi_v2.1"
set "SHIELD_USE_GLINER=true"
set "SHIELD_DETECTOR_MODE=gliner"
if not defined SHIELD_ACTION_MODEL_PATH set "SHIELD_ACTION_MODEL_PATH=%~dp0app\models\necessity_action.joblib"
set "LLM_MODE=mock"
echo Official GLiNER baseline, local inference and mock generation.
echo Evaluation page: http://127.0.0.1:8787/evaluation
call "%~dp0tools\windows\启动隐盾.cmd" --offline %*
exit /b %errorlevel%
