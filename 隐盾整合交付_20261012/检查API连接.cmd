@echo off
chcp 65001 >nul
cd /d "%~dp0app"
call "..\运行Python.cmd" -X utf8 -m llm_shield.api_check --connect
pause
