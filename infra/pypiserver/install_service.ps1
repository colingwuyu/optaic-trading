param(
  [string]$BaseDir = "D:\optaic-pypi",
  [string]$ServiceName = "OptAIC-PyPIServer",
  [int]$Port = 8080,
  [string]$Bind = "0.0.0.0"
)

$PackagesDir = Join-Path $BaseDir "packages"
$AuthFile = Join-Path $BaseDir "auth\htpasswd.txt"
$LogsDir = Join-Path $BaseDir "logs"
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

if (Get-Command nssm -ErrorAction SilentlyContinue) {
  $args = "run -p $Port -i $Bind --disable-fallback -P `"$AuthFile`" `"$PackagesDir`""
  nssm install $ServiceName "pypi-server" $args
  nssm set $ServiceName AppStdout (Join-Path $LogsDir "pypiserver.log")
  nssm set $ServiceName AppStderr (Join-Path $LogsDir "pypiserver.log")
  nssm start $ServiceName
  Write-Host "Service installed with NSSM: $ServiceName"
} else {
  Write-Host "NSSM not found. Install NSSM or use Task Scheduler."
  Write-Host "Example scheduled task command:"
  Write-Host "pypi-server run -p $Port -i $Bind --disable-fallback -P `"$AuthFile`" `"$PackagesDir`""
}
