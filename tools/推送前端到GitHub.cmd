@echo off
chcp 65001 >nul
setlocal
rem ── 隐盾：把前端改动推到 GitHub 的 frontend 分支 ──
rem ⚠ 前端**不进 main**。main 只保留原始交付代码，前端改动一律走 frontend。
rem 本机 git 在 D:\APP\Git，已进 PATH；同目录放了一份完整路径作兜底。
set "GIT=git"
where git >nul 2>nul || set "GIT=D:\APP\Git\cmd\git.exe"
set "REPO=%~dp0."
set "BRANCH=frontend"

echo ============================================================
echo  仓库：D:\project\LLM-shield
echo  远端：https://github.com/Luzifeng0125/LLM-shield.git
echo  推送分支：%BRANCH%   （main 保持不动）
echo ============================================================
echo.

for /f "delims=" %%b in ('"%GIT%" -C "%REPO%" rev-parse --abbrev-ref HEAD') do set "CUR=%%b"
if /i not "%CUR%"=="%BRANCH%" (
  echo [注意] 当前在分支 "%CUR%"，不是 %BRANCH%。
  echo        先切换： "%GIT%" -C "%REPO%" checkout %BRANCH%
  echo.
  pause & exit /b 1
)

echo ── 将要推送的提交 ──
"%GIT%" -C "%REPO%" log --oneline origin/%BRANCH%..HEAD
echo.
echo ── 改动概览 ──
"%GIT%" -C "%REPO%" diff --stat origin/%BRANCH%..HEAD
echo.
echo ── 工作区状态（未提交的改动不会被推送） ──
"%GIT%" -C "%REPO%" status --short
echo.
echo 凭据已存在 Windows 凭据管理器，正常情况不会再弹登录窗口。
echo.
pause
echo ── 开始推送 ──
"%GIT%" -C "%REPO%" push origin %BRANCH%
if errorlevel 1 goto :fail
echo.
echo [成功] 已推送到 frontend 分支：
echo        https://github.com/Luzifeng0125/LLM-shield/tree/frontend
echo        需要合并到 main 时，在该页面点 "Compare ^& pull request"。
pause & exit /b 0

:fail
echo.
echo [失败] 请把上面的错误信息复制给我。
pause & exit /b 1
