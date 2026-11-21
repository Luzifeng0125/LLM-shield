@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0..\..\app"
set "LLM_MODE=mock"
set "PYTHONDONTWRITEBYTECODE=1"
call "%~dp0运行Python.cmd" -X utf8 tests/test_smoke.py
if errorlevel 1 exit /b 1
call "%~dp0运行Python.cmd" -X utf8 -m pytest tests --ignore=tests/test_smoke.py --ignore=tests/test_gliner_v3.py --ignore=tests/test_field_v1.py -p no:cacheprovider -q
exit /b %errorlevel%
