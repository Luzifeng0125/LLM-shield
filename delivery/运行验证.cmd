@echo off
chcp 65001 >nul
cd /d "%~dp0app"
set LLM_MODE=mock
set PYTHONDONTWRITEBYTECODE=1
call "..\运行Python.cmd" -X utf8 tests/test_smoke.py
if errorlevel 1 goto failed
call "..\运行Python.cmd" -X utf8 -m pytest tests --ignore=tests/test_smoke.py "..\数据集\复核与训练执行包_20261014\scripts" -p no:cacheprovider -q --junitxml="outputs\verification\pytest.xml"
if errorlevel 1 goto failed
echo Verification completed.
exit /b 0
:failed
echo Verification failed. See the output above.
exit /b 1
