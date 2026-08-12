# Scriptorium one-time setup (Windows PowerShell).
# Checks your tools, installs the server, and builds the two web apps so a single
# server can serve both. Safe to re-run. macOS / Linux: use scripts/setup.sh.
#
# If PowerShell blocks the script, allow it for this session with:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Say($m) { Write-Host "`n» $m" -ForegroundColor Magenta }
function Ok($m)  { Write-Host "  [ok] $m" -ForegroundColor Green }
function Die($m) { Write-Host "`n[x] $m" -ForegroundColor Red; exit 1 }
function Have($c) { $null -ne (Get-Command $c -ErrorAction SilentlyContinue) }

Say "Checking your tools"
if (-not (Have 'uv'))   { Die "'uv' is not installed. Get it at https://docs.astral.sh/uv/ then run this again." }
Ok "uv"
if (-not (Have 'node')) { Die "'node' (Node.js 20+) is not installed. Get it at https://nodejs.org then run this again." }
Ok "node $(node --version)"
if (-not (Have 'npm'))  { Die "'npm' is missing (it comes with Node.js). Reinstall Node from https://nodejs.org." }
Ok "npm"

Say "Installing the server (uv sync)"
Push-Location server; uv sync; if ($LASTEXITCODE) { Die "uv sync failed." }; Pop-Location
Ok "server dependencies ready"

Say "Building the reader app"
Push-Location reader; npm install; if ($LASTEXITCODE) { Die "npm install (reader) failed." }
npm run build; if ($LASTEXITCODE) { Die "reader build failed." }; Pop-Location
Ok "reader built (reader/dist)"

Say "Building the admin app"
Push-Location admin-ui; npm install; if ($LASTEXITCODE) { Die "npm install (admin-ui) failed." }
npm run build; if ($LASTEXITCODE) { Die "admin build failed." }; Pop-Location
Ok "admin built (admin-ui/dist)"

$DataDir = if ($env:SCRIPTORIUM_DATA) { $env:SCRIPTORIUM_DATA } else { Join-Path $Root 'scriptorium-data' }
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
Ok "library folder ready at $DataDir"

Say "All set!"
Write-Host "Next, start the server with:`n`n    .\scripts\start.ps1`n`nThen open http://localhost:8720 (reader) and http://localhost:8720/admin (bakery).`n"
