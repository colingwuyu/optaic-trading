param(
  [Parameter(Mandatory = $true)]
  [string]$RepoBaseUrl,
  [string]$PackageName = "optaic"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Normalize-RepoBase {
  param([string]$Url)
  $trimmed = $Url.TrimEnd("/")
  if ($trimmed.EndsWith("/simple")) {
    return $trimmed.Substring(0, $trimmed.Length - 7)
  }
  return $trimmed
}

$repoBase = Normalize-RepoBase -Url $RepoBaseUrl
$indexUrl = "$repoBase/simple/$PackageName/"

$headers = @{}
$artiUser = $env:OPTAIC_ARTI_USER
$artiPass = $env:OPTAIC_ARTI_PASS
if ($artiUser -and $artiPass) {
  $token = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("$artiUser`:$artiPass"))
  $headers["Authorization"] = "Basic $token"
}

$response = Invoke-WebRequest -Uri $indexUrl -UseBasicParsing -Headers $headers
$pattern = [Regex]::Escape($PackageName) + "-([0-9A-Za-z][0-9A-Za-z\\.\\+\\-]*)"
$matches = [Regex]::Matches($response.Content, $pattern)
$versions = @()
foreach ($match in $matches) {
  $versions += $match.Groups[1].Value
}
$versions = $versions | Sort-Object -Unique

if (-not $versions) {
  Write-Host "No versions found for $PackageName at $indexUrl"
  exit 0
}

$semver = @()
$nonSemver = @()
foreach ($version in $versions) {
  try {
    [Version]$version | Out-Null
    $semver += $version
  } catch {
    $nonSemver += $version
  }
}

$sorted = @()
if ($semver.Count -gt 0) {
  $sorted += ($semver | Sort-Object { [Version]$_ })
}
if ($nonSemver.Count -gt 0) {
  $sorted += ($nonSemver | Sort-Object)
}

$latest = $sorted[-1]
Write-Host "Available versions:"
$sorted | ForEach-Object { Write-Host "  $_" }
Write-Host "Latest: $latest"
