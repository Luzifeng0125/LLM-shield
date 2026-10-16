@echo off
chcp 65001 >nul
title 隐盾 LLM-Shield · 停止服务

set "PORT=8787"
if not "%~1"=="" set "PORT=%~1"

echo 查找监听 %PORT% 端口的进程...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$c = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue; if (-not $c) { Write-Host '  没有进程在监听 %PORT%'; exit 0 }; $c | ForEach-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; Write-Host ('  结束 ' + $p.ProcessName + ' (PID ' + $_.OwningProcess + ')'); Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }; Start-Sleep -Milliseconds 400; $still = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue; if ($still) { Write-Host '  [警告] 端口仍被占用' } else { Write-Host '  已停止，端口 %PORT% 已释放' }"

echo.
pause
