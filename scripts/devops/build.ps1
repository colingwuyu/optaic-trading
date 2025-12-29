param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-PythonCommand {
  $candidates = @(
    @{ Cmd = "python"; Args = @() },
    @{ Cmd = "py"; Args = @("-3.12") },
    @{ Cmd = "py"; Args = @("-3.11") },
    @{ Cmd = "py"; Args = @() }
  )
  foreach ($candidate in $candidates) {
    if (-not (Get-Command $candidate.Cmd -ErrorAction SilentlyContinue)) { continue }
    return $candidate
  }
  throw "Python not found on PATH."
}

function Invoke-Python {
  param([string[]]$PyArgs)
  $python = Get-PythonCommand
  $cmd = $python.Cmd
  $cmdArgs = @()
  if ($python.Args) { $cmdArgs += $python.Args }
  $cmdArgs += $PyArgs
  & $cmd @cmdArgs
}

function Get-ProjectVersion {
  param([string]$PyProjectPath)
  $match = Select-String -Path $PyProjectPath -Pattern '^\s*version\s*=' | Select-Object -First 1
  if ($match -and $match.Line -match 'version\s*=\s*"([^"]+)"') {
    return $matches[1]
  }
  throw "Could not read version from pyproject.toml."
}

$pyproject = Join-Path $RepoRoot "pyproject.toml"
if (-not (Test-Path $pyproject)) {
  throw "pyproject.toml not found at $pyproject"
}

Push-Location $RepoRoot
$cleanupDb = $false
$dbFile = $null
$previousDbUrl = $env:DATABASE_URL
try {
  Invoke-Python -PyArgs @("-m", "ruff", "check", ".")
  if ($LASTEXITCODE -ne 0) {
    throw "ruff failed."
  }
  if (-not $env:DATABASE_URL) {
    $tempDbDir = Join-Path $env:TEMP "optaic-test-db"
    New-Item -ItemType Directory -Force -Path $tempDbDir | Out-Null
    $dbFile = Join-Path $tempDbDir ("optaic-test-" + [guid]::NewGuid().ToString("N") + ".sqlite")
    $dbPath = $dbFile -replace "\\\\", "/"
    $env:DATABASE_URL = "sqlite+aiosqlite:///$dbPath"
    $cleanupDb = $true
    Invoke-Python -PyArgs @(
      "-c",
      "from optaic.runtime.migrate import run_migrations; run_migrations(r'$env:DATABASE_URL')"
    )
  }
  Invoke-Python -PyArgs @("-m", "pytest")
  if ($LASTEXITCODE -ne 0) {
    throw "pytest failed."
  }
  Invoke-Python -PyArgs @("-m", "build")
  if ($LASTEXITCODE -ne 0) {
    throw "build failed."
  }
  $version = Get-ProjectVersion -PyProjectPath $pyproject
  Write-Host "Built OptAIC version $version"
} finally {
  if ($cleanupDb -and $dbFile -and (Test-Path $dbFile)) {
    Remove-Item -Force -Path $dbFile -ErrorAction SilentlyContinue
  }
  if ($null -eq $previousDbUrl) {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
  } else {
    $env:DATABASE_URL = $previousDbUrl
  }
  Pop-Location
}
