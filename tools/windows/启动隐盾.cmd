@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
call "%~dp0运行Python.cmd" -X utf8 "%~dp0..\..\app\scripts\start_service.py" %*
exit /b %errorlevel%
