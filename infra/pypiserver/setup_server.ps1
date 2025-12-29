param(
  [string]$BaseDir = "D:\optaic-pypi",
  [string]$User = "optaic",
  [string]$Password = "change-me"
)

$PackagesDir = Join-Path $BaseDir "packages"
$AuthDir = Join-Path $BaseDir "auth"
$LogsDir = Join-Path $BaseDir "logs"
$HtpasswdPath = Join-Path $AuthDir "htpasswd.txt"

New-Item -ItemType Directory -Force -Path $PackagesDir | Out-Null
New-Item -ItemType Directory -Force -Path $AuthDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

python -m pip install --upgrade pip | Out-Null
python -m pip install pypiserver passlib | Out-Null

if (Get-Command htpasswd -ErrorAction SilentlyContinue) {
  htpasswd -b -c $HtpasswdPath $User $Password | Out-Null
} else {
  @"
from passlib.apache import HtpasswdFile
ht = HtpasswdFile()
ht.set_password("$User", "$Password")
ht.save("$HtpasswdPath")
"@ | python -
}

Write-Host "Setup complete."
Write-Host "Packages dir: $PackagesDir"
Write-Host "Auth file: $HtpasswdPath"
Write-Host "Run: .\infra\pypiserver\run_pypiserver.ps1"
