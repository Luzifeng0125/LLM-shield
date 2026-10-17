param([ValidateRange(1024, 65535)][int]$Port = 8787)
$ErrorActionPreference = 'Stop'
$launcher = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'app\scripts\start_service.py'))
$connections = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if (-not $connections) { Write-Output "No listener on port $Port."; exit 0 }
foreach ($ownerId in @($connections.OwningProcess | Select-Object -Unique)) {
    $service = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerId"
    if (-not $service.CommandLine -or -not $service.CommandLine.Contains($launcher)) {
        throw "Port $Port belongs to another process. It was not stopped."
    }
    Stop-Process -Id $ownerId -ErrorAction Stop
    Write-Output "Stopped the local shield service (PID $ownerId)."
}
