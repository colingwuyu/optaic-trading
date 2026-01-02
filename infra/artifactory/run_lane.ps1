param(
  [ValidateSet("staging", "uat", "prod")]
  [string]$Lane = "staging",
  [string]$BaseDir = "C:\optaic-artifactory",
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
    @{ Cmd = "C:\Users\colin\source\repos\optaic-trading\venv312\Scripts\python.exe"; Args = @() },
    @{ Cmd = "C:\Users\colin\source\repos\optaic-trading\.venv\Scripts\python.exe"; Args = @() },
    @{ Cmd = "python"; Args = @() },
    @{ Cmd = "py"; Args = @() }
  )
  foreach ($candidate in $candidates) {
    if (-not (Get-Command $candidate.Cmd -ErrorAction SilentlyContinue)) { continue }
    return $candidate
  }
  throw "Python is required."
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
