param(
  [ValidateSet("staging", "uat", "prod")]
  [string]$Lane = "staging",
  [Parameter(Mandatory = $true)]
  [string]$RepoBaseUrl,
  [string]$PackageName = "optaic",
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

function Normalize-RepoBase {
  param([string]$Url)
  $trimmed = $Url.TrimEnd("/")
  if ($trimmed.EndsWith("/simple")) {
    return $trimmed.Substring(0, $trimmed.Length - 7)
  }
  return $trimmed
}

function Get-PackageVersion {
  param([System.IO.FileInfo[]]$Files, [string]$Name)
  $versions = @()
  foreach ($file in $Files) {
    if ($file.Name -match "^$Name-([0-9A-Za-z][0-9A-Za-z.+]*?)(?:-|\.tar\.gz|$)") {
      $versions += $matches[1]
    }
  }
  $unique = @($versions | Sort-Object -Unique)
  if ($unique.Count -eq 0) {
    throw "Could not determine version from dist artifacts."
  }
  if ($unique.Count -gt 1) {
    throw "Multiple versions found in dist: $($unique -join ", ")"
  }
  return $unique[0]
}

$artiUser = $env:OPTAIC_ARTI_USER
$artiPass = $env:OPTAIC_ARTI_PASS
if (-not $artiUser -or -not $artiPass) {
  throw "Set OPTAIC_ARTI_USER and OPTAIC_ARTI_PASS before publishing."
}

$distDir = Join-Path $RepoRoot "dist"
if (-not (Test-Path $distDir)) {
  throw "dist/ not found. Run build.ps1 first."
}

$wheelFiles = Get-ChildItem -Path $distDir -Filter "$PackageName-*.whl"
$sdistFiles = Get-ChildItem -Path $distDir -Filter "$PackageName-*.tar.gz"
if (-not $wheelFiles -or -not $sdistFiles) {
  throw "Missing dist artifacts for $PackageName. Expected wheel and sdist."
}

$version = Get-PackageVersion -Files (@($wheelFiles) + @($sdistFiles)) -Name $PackageName
$repoBase = Normalize-RepoBase -Url $RepoBaseUrl
$repoUrl = "$repoBase/"
$indexUrl = "$repoBase/simple/$PackageName/"

Push-Location $RepoRoot
try {
  Invoke-Python -PyArgs @(
    "-m", "twine", "upload",
    "--non-interactive",
    "--repository-url", $repoUrl,
    "-u", $artiUser,
    "-p", $artiPass,
    "dist\\$PackageName-*.whl",
    "dist\\$PackageName-*.tar.gz"
  )
} finally {
  Pop-Location
}

$headers = @{}
if ($artiUser -and $artiPass) {
  $token = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("$artiUser`:$artiPass"))
  $headers["Authorization"] = "Basic $token"
}

$response = Invoke-WebRequest -Uri $indexUrl -UseBasicParsing -Headers $headers
$escaped = [Regex]::Escape("$PackageName-$version")
if ($response.Content -notmatch $escaped) {
  throw "Upload verification failed. Version $version not found at $indexUrl"
}

Write-Host "Published $PackageName $version to $Lane ($indexUrl)"
