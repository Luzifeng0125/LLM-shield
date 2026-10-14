@echo off
if exist "%~dp0runtime\python\python.exe" goto portable
if exist "%~dp0app\.venv\Scripts\python.exe" goto venv
echo Python environment missing. Run the setup PowerShell script in this folder first.
exit /b 1
:portable
"%~dp0runtime\python\python.exe" %*
exit /b %errorlevel%
:venv
"%~dp0app\.venv\Scripts\python.exe" %*
exit /b %errorlevel%
