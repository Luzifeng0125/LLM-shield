@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_local_service.ps1" %*
exit /b %errorlevel%
