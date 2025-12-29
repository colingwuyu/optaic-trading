param(
  [ValidateSet("patch","minor","major")]
  [string]$VersionBump = ""
)

$root = Split-Path -Parent $PSScriptRoot
$pyproject = Join-Path $root "pyproject.toml"

if ($VersionBump) {
  $content = Get-Content -Path $pyproject -Raw
  if ($content -match '(?m)^version\\s*=\\s*\"(\\d+)\\.(\\d+)\\.(\\d+)\"') {
    $major = [int]$matches[1]
    $minor = [int]$matches[2]
    $patch = [int]$matches[3]
    switch ($VersionBump) {
      "major" { $major++; $minor = 0; $patch = 0 }
      "minor" { $minor++; $patch = 0 }
      "patch" { $patch++ }
    }
    $newLine = "version = `"$major.$minor.$patch`""
    $content = [regex]::Replace($content, '(?m)^version\\s*=\\s*\"\\d+\\.\\d+\\.\\d+\"', $newLine, 1)
    Set-Content -Path $pyproject -Value $content -Encoding UTF8
    Write-Host "Bumped version to $major.$minor.$patch"
  } else {
    throw "Could not find version in pyproject.toml"
  }
}

python (Join-Path $PSScriptRoot "release_build.py")
python (Join-Path $PSScriptRoot "release_publish.py")
