@echo off
chcp 65001 >nul
cd /d "%~dp0app"
set LLM_MODE=mock
call "..\运行Python.cmd" -X utf8 tests/test_smoke.py
if errorlevel 1 goto failed
call "..\运行Python.cmd" -X utf8 -m pytest tests --ignore=tests/test_smoke.py -q --junitxml="..\验证结果\pytest.xml"
if errorlevel 1 goto failed
call "..\运行Python.cmd" -X utf8 eval/run_eval.py --split test --out "..\验证结果\材料脱敏评测.json"
if errorlevel 1 goto failed
echo Verification completed.
pause
exit /b 0
:failed
echo Verification failed. See the output above.
pause
exit /b 1
