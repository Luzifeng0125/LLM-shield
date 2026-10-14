@echo off
chcp 65001 >nul
cd /d "%~dp0app"
echo LLM-Shield - local Python environment
echo Conversation: http://127.0.0.1:8787/
echo Keep this window open. Press Ctrl+C to stop.
call "..\运行Python.cmd" -X utf8 run.py --host 127.0.0.1 --port 8787
if errorlevel 1 pause
