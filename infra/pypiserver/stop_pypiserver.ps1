param(
  [string]$BaseDir = "D:\optaic-pypi"
)

$PidFile = Join-Path $BaseDir "logs\pypiserver.pid"
if (-not (Test-Path $PidFile)) {
  Write-Host "PID file not found: $PidFile"
  exit 1
}

$pid = Get-Content -Path $PidFile | Select-Object -First 1
if ($pid) {
  Stop-Process -Id $pid -Force
  Remove-Item -Path $PidFile -Force
  Write-Host "Stopped pypiserver (PID $pid)"
} else {
  Write-Host "PID file is empty."
}
