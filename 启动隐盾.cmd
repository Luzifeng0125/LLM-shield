@echo off
chcp 65001 >nul
call "%~dp0delivery\启动隐盾.cmd" %*
exit /b %errorlevel%
