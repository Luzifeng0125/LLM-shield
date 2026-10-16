@echo off
chcp 65001 >nul
cd /d "%~dp0app"
echo This retrains the local classifier using existing synthetic development data.
echo Stop the service before retraining. Restart it afterward.
call "..\运行Python.cmd" -X utf8 -m llm_shield.m4_necessity.train
pause
