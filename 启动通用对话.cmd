@echo off
chcp 65001 >nul
call "%~dp0delivery\启动通用对话.cmd" %*
exit /b %errorlevel%
