param(
  [string]$BaseDir = "D:\optaic-pypi",
  [int]$Port = 8080,
  [string]$Bind = "0.0.0.0"
)

$PackagesDir = Join-Path $BaseDir "packages"
$AuthFile = Join-Path $BaseDir "auth\htpasswd.txt"
$LogsDir = Join-Path $BaseDir "logs"
$LogFile = Join-Path $LogsDir "pypiserver.log"
$PidFile = Join-Path $LogsDir "pypiserver.pid"

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

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
  -RedirectStandardOutput $LogFile -RedirectStandardError $LogFile

$proc.Id | Set-Content -Path $PidFile -Encoding ASCII
Write-Host "pypiserver started (PID $($proc.Id))"
Write-Host "Log: $LogFile"
