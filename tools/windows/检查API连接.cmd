@echo off
chcp 65001 >nul
cd /d "%~dp0..\..\app"
call "%~dp0运行Python.cmd" -X utf8 -m llm_shield.api_check --connect
pause
