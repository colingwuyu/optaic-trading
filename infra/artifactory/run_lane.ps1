param(
  [ValidateSet("staging", "uat", "prod")]
  [string]$Lane = "staging",
  [string]$BaseDir = "D:\optaic-artifactory",
  [int]$Port = 0,
  [string]$Bind = "0.0.0.0",
  [string]$PackagesDir = "",
  [string]$Htpasswd = ""
)

$lane = $Lane.ToLower()
if ($Port -le 0) {
  switch ($lane) {
    "staging" { $Port = 8081 }
    "uat" { $Port = 8082 }
    "prod" { $Port = 8083 }
  }
}

if (-not $PackagesDir) {
  $PackagesDir = Join-Path $BaseDir "$lane\packages"
}

$defaultAuth = Join-Path $BaseDir "auth\htpasswd.txt"
$laneAuth = Join-Path $BaseDir "auth\htpasswd-$lane.txt"
if ($Htpasswd) {
  $AuthFile = $Htpasswd
} elseif (Test-Path $laneAuth) {
  $AuthFile = $laneAuth
} else {
  $AuthFile = $defaultAuth
}

$LogsDir = Join-Path $BaseDir "logs"
$LogFile = Join-Path $LogsDir "pypiserver-$lane.out.log"
$ErrFile = Join-Path $LogsDir "pypiserver-$lane.err.log"
$PidFile = Join-Path $LogsDir "pypiserver-$lane.pid"

New-Item -ItemType Directory -Force -Path $PackagesDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

function Get-PythonCommand {
  $candidates = @(
    @{ Cmd = "py"; Args = @("-3.12") },
    @{ Cmd = "py"; Args = @("-3.11") },
    @{ Cmd = "py"; Args = @("-3.10") },
    @{ Cmd = "python"; Args = @() },
    @{ Cmd = "py"; Args = @() }
  )
  foreach ($candidate in $candidates) {
    if (-not (Get-Command $candidate.Cmd -ErrorAction SilentlyContinue)) { continue }
    try {
      $ver = & $candidate.Cmd @($candidate.Args + @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"))
    } catch {
      continue
    }
    if (-not $ver) { continue }
    $parts = $ver.Trim().Split(".")
    if ($parts.Length -lt 2) { continue }
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 13)) { continue }
    return $candidate
  }
  throw "Python 3.12 or lower is required for pypiserver (Python 3.13 removed 'cgi')."
}

$args = @(
  "run",
  "--server", "wsgiref",
  "--overwrite",
  "-p", "$Port",
  "-i", "$Bind",
  "--disable-fallback",
  "-P", "$AuthFile",
  "$PackagesDir"
)

$startCmd = "pypi-server"
$startArgs = $args
if (-not (Get-Command $startCmd -ErrorAction SilentlyContinue)) {
  $py = Get-PythonCommand
  $startCmd = $py.Cmd
  $startArgs = @()
  if ($py.Args) { $startArgs += $py.Args }
  $startArgs += @("-m", "pypiserver") + $args
}

$proc = Start-Process -FilePath $startCmd -ArgumentList $startArgs -PassThru `
  -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile

$proc.Id | Set-Content -Path $PidFile -Encoding ASCII
Write-Host "Lane $lane started (PID $($proc.Id))"
Write-Host "URL: http://$Bind`:$Port/simple/"
Write-Host "Log: $LogFile"
Write-Host "Err: $ErrFile"
