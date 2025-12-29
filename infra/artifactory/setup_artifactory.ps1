param(
  [string]$BaseDir = "D:\optaic-artifactory",
  [string]$User = "optaic",
  [string]$Password = "change-me",
  [switch]$PerLaneAuth
)

$StagingDir = Join-Path $BaseDir "staging\packages"
$UatDir = Join-Path $BaseDir "uat\packages"
$ProdDir = Join-Path $BaseDir "prod\packages"
$AuthDir = Join-Path $BaseDir "auth"
$LogsDir = Join-Path $BaseDir "logs"
$DefaultHtpasswd = Join-Path $AuthDir "htpasswd.txt"

New-Item -ItemType Directory -Force -Path $StagingDir | Out-Null
New-Item -ItemType Directory -Force -Path $UatDir | Out-Null
New-Item -ItemType Directory -Force -Path $ProdDir | Out-Null
New-Item -ItemType Directory -Force -Path $AuthDir | Out-Null
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

function Write-Htpasswd {
  param(
    [string]$TargetPath
  )
  if (Get-Command htpasswd -ErrorAction SilentlyContinue) {
    htpasswd -b -c $TargetPath $User $Password | Out-Null
    return
  }
  $python = Get-PythonCommand
  $pyCmd = $python.Cmd
  $pyArgs = @()
  if ($python.Args) { $pyArgs += $python.Args }
  @"
from passlib.apache import HtpasswdFile
ht = HtpasswdFile()
ht.set_password("$User", "$Password")
ht.save(r"$TargetPath")
"@ | & $pyCmd @($pyArgs + @("-"))
}

$pythonCmd = Get-PythonCommand
$pyCmd = $pythonCmd.Cmd
$pyArgs = @()
if ($pythonCmd.Args) { $pyArgs += $pythonCmd.Args }
& $pyCmd @($pyArgs + @("-m", "pip", "--version")) | Out-Null
if ($LASTEXITCODE -ne 0) {
  & $pyCmd @($pyArgs + @("-m", "ensurepip", "--upgrade")) | Out-Null
}
& $pyCmd @($pyArgs + @("-m", "pip", "install", "--upgrade", "pip")) | Out-Null
& $pyCmd @($pyArgs + @("-m", "pip", "install", "pypiserver", "passlib")) | Out-Null

if ($PerLaneAuth) {
  Write-Htpasswd -TargetPath (Join-Path $AuthDir "htpasswd-staging.txt")
  Write-Htpasswd -TargetPath (Join-Path $AuthDir "htpasswd-uat.txt")
  Write-Htpasswd -TargetPath (Join-Path $AuthDir "htpasswd-prod.txt")
} else {
  Write-Htpasswd -TargetPath $DefaultHtpasswd
}

$runLaneScript = Join-Path $PSScriptRoot "run_lane.ps1"
$installServiceScript = Join-Path $PSScriptRoot "install_lane_service.ps1"

@"
param()
& "$runLaneScript" -Lane "staging" -BaseDir "$BaseDir" -Port 8081
"@ | Set-Content -Path (Join-Path $BaseDir "run-staging.ps1") -Encoding ASCII

@"
param()
& "$runLaneScript" -Lane "uat" -BaseDir "$BaseDir" -Port 8082
"@ | Set-Content -Path (Join-Path $BaseDir "run-uat.ps1") -Encoding ASCII

@"
param()
& "$runLaneScript" -Lane "prod" -BaseDir "$BaseDir" -Port 8083
"@ | Set-Content -Path (Join-Path $BaseDir "run-prod.ps1") -Encoding ASCII

if (Test-Path $installServiceScript) {
  @"
param()
& "$installServiceScript" -Lane "staging" -BaseDir "$BaseDir" -Port 8081
"@ | Set-Content -Path (Join-Path $BaseDir "install-staging-service.ps1") -Encoding ASCII

  @"
param()
& "$installServiceScript" -Lane "uat" -BaseDir "$BaseDir" -Port 8082
"@ | Set-Content -Path (Join-Path $BaseDir "install-uat-service.ps1") -Encoding ASCII

  @"
param()
& "$installServiceScript" -Lane "prod" -BaseDir "$BaseDir" -Port 8083
"@ | Set-Content -Path (Join-Path $BaseDir "install-prod-service.ps1") -Encoding ASCII
}

Write-Host "Artifactory setup complete."
Write-Host "Base dir: $BaseDir"
Write-Host "Auth: $AuthDir"
Write-Host "Start lanes:"
Write-Host "  $runLaneScript -Lane staging"
Write-Host "  $runLaneScript -Lane uat"
Write-Host "  $runLaneScript -Lane prod"
