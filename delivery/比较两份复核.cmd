@echo off
chcp 65001 >nul
if "%~2"=="" goto usage
cd /d "%~dp0app"
call "..\运行Python.cmd" -X utf8 scripts/compare_reviews.py "%~1" "%~2" --out "..\人工复核\裁决待填写.json"
pause
exit /b
:usage
echo 请将两份复核 JSON 文件一起拖到此脚本，或把文件路径告诉开发人员。
echo 如果已有裁决待填写.json，请先保存并另存旧记录；工具不会覆盖它。
pause
