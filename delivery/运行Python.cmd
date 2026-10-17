@echo off
if exist "%~dp0runtime\training_env\Scripts\python.exe" goto current
if exist "%~dp0app\.venv\Scripts\python.exe" goto venv
echo Python environment missing. Run the setup PowerShell script in this folder first.
exit /b 1
:current
"%~dp0runtime\training_env\Scripts\python.exe" -B %*
exit /b %errorlevel%
:venv
"%~dp0app\.venv\Scripts\python.exe" -B %*
exit /b %errorlevel%
