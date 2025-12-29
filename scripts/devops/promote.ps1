param(
  [ValidateSet("staging", "uat")]
  [string]$FromLane,
  [ValidateSet("uat", "prod")]
  [string]$ToLane,
  [Parameter(Mandatory = $true)]
  [string]$Version,
  [string]$ArtifactoryRoot = "D:\\optaic-artifactory",
  [string]$PackageName = "optaic",
  [string]$ApprovalFile = "",
  [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($FromLane -eq "staging" -and $ToLane -ne "uat") {
  throw "staging can only promote to uat."
}
if ($FromLane -eq "uat" -and $ToLane -ne "prod") {
  throw "uat can only promote to prod."
}
$approval = $null
$approvalFile = $ApprovalFile
if (-not $approvalFile) {
  $approvalFile = Join-Path $ArtifactoryRoot "approvals\\$Version\\${ToLane}_approved.json"
}

if (-not $Force) {
  if (-not (Test-Path $approvalFile)) {
    throw "Approval file not found: $approvalFile. Use -Force to bypass."
  }
  try {
    $approval = Get-Content -Raw -Path $approvalFile | ConvertFrom-Json
  } catch {
    throw "Failed to parse approval file: $approvalFile"
  }
  $required = @("version", "from_lane", "to_lane", "approved_by", "approved_at", "ticket_id", "notes")
  $missing = @()
  foreach ($field in $required) {
    if (-not ($approval.PSObject.Properties.Name -contains $field)) {
      $missing += $field
      continue
    }
    if ($null -eq $approval.$field) {
      $missing += $field
    }
  }
  if ($missing.Count -gt 0) {
    throw "Approval file missing fields: $($missing -join ', ')"
  }
  if ("$($approval.version)" -ne $Version) {
    throw "Approval version mismatch: expected $Version, got $($approval.version)"
  }
  if ("$($approval.from_lane)".ToLower() -ne $FromLane) {
    throw "Approval from_lane mismatch: expected $FromLane, got $($approval.from_lane)"
  }
  if ("$($approval.to_lane)".ToLower() -ne $ToLane) {
    throw "Approval to_lane mismatch: expected $ToLane, got $($approval.to_lane)"
  }
}

$fromDir = Join-Path $ArtifactoryRoot "$FromLane\\packages"
$toDir = Join-Path $ArtifactoryRoot "$ToLane\\packages"
$logDir = Join-Path $ArtifactoryRoot "logs"
$logFile = Join-Path $logDir "promotion.log"

if (-not (Test-Path $fromDir)) {
  throw "Source lane directory not found: $fromDir"
}
New-Item -ItemType Directory -Force -Path $toDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$wheelFiles = Get-ChildItem -Path $fromDir -Filter "$PackageName-$Version-*.whl"
if (-not $wheelFiles) {
  throw "No wheel found for $PackageName $Version in $fromDir"
}
$sdistFiles = Get-ChildItem -Path $fromDir -Filter "$PackageName-$Version*.tar.gz"

$artifacts = @()
foreach ($file in (@($wheelFiles) + @($sdistFiles))) {
  $dest = Join-Path $toDir $file.Name
  Copy-Item -Path $file.FullName -Destination $dest -Force
  $artifacts += $file.Name
}

$entry = @{
  timestamp = (Get-Date).ToString("o")
  from = $FromLane
  to = $ToLane
  version = $Version
  package = $PackageName
  artifacts = $artifacts
  user = $env:USERNAME
  approval_file = if ($approvalFile -and (Test-Path $approvalFile)) { $approvalFile } else { $null }
  approval = if ($approval) {
    @{
      version = $approval.version
      from_lane = $approval.from_lane
      to_lane = $approval.to_lane
      approved_by = $approval.approved_by
      approved_at = $approval.approved_at
      ticket_id = $approval.ticket_id
      notes = $approval.notes
    }
  } else {
    $null
  }
  forced = [bool]$Force
}
$line = ($entry | ConvertTo-Json -Compress)
Add-Content -Path $logFile -Value $line -Encoding ASCII

Write-Host "Promoted $PackageName $Version from $FromLane to $ToLane."
