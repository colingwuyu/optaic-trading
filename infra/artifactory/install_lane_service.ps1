param(
  [ValidateSet("staging", "uat", "prod")]
  [string]$Lane = "staging",
  [string]$BaseDir = "D:\optaic-artifactory",
  [int]$Port = 0,
  [string]$Bind = "0.0.0.0",
  [string]$ServiceName = ""
)

$lane = $Lane.ToLower()
if ($Port -le 0) {
  switch ($lane) {
    "staging" { $Port = 8081 }
    "uat" { $Port = 8082 }
    "prod" { $Port = 8083 }
  }
}

if (-not $ServiceName) {
  $ServiceName = "OptAIC-Artifactory-$lane"
}

$PackagesDir = Join-Path $BaseDir "$lane\packages"
$defaultAuth = Join-Path $BaseDir "auth\htpasswd.txt"
$laneAuth = Join-Path $BaseDir "auth\htpasswd-$lane.txt"
$AuthFile = if (Test-Path $laneAuth) { $laneAuth } else { $defaultAuth }
$LogsDir = Join-Path $BaseDir "logs"
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

if (Get-Command nssm -ErrorAction SilentlyContinue) {
  if (Get-Command pypi-server -ErrorAction SilentlyContinue) {
    $args = "run -p $Port -i $Bind --disable-fallback -P `"$AuthFile`" `"$PackagesDir`""
    nssm install $ServiceName "pypi-server" $args
  } else {
    $py = Get-PythonCommand
    $pyArgs = @()
    if ($py.Args) { $pyArgs += $py.Args }
    $pyArgs += @("-m", "pypiserver", "run", "-p", "$Port", "-i", "$Bind", "--disable-fallback", "-P", $AuthFile, $PackagesDir)
    nssm install $ServiceName $py.Cmd ($pyArgs -join " ")
  }
  nssm set $ServiceName AppStdout (Join-Path $LogsDir "pypiserver-$lane.log")
  nssm set $ServiceName AppStderr (Join-Path $LogsDir "pypiserver-$lane.log")
  nssm start $ServiceName
  Write-Host "Service installed with NSSM: $ServiceName"
  return
}

$runLane = Join-Path $PSScriptRoot "run_lane.ps1"
$taskCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$runLane`" -Lane $lane -BaseDir `"$BaseDir`" -Port $Port -Bind `"$Bind`""
try {
  schtasks /Create /TN $ServiceName /TR $taskCmd /SC ONSTART /RL HIGHEST /F | Out-Null
  schtasks /Run /TN $ServiceName | Out-Null
  Write-Host "Scheduled task created: $ServiceName"
} catch {
  Write-Host "Failed to create scheduled task. Try running as Administrator."
  Write-Host "Task command:"
  Write-Host $taskCmd
}
