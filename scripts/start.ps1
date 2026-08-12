# Start the Scriptorium bakery server (Windows PowerShell).
# Serves the reader at / and the admin app at /admin on port 8720.
# Run scripts\setup.ps1 first. macOS / Linux: use scripts/start.sh.
#
# Honors these environment variables if you set them (all optional):
#   SCRIPTORIUM_DATA   where your library lives   (default: .\scriptorium-data)
#   SCRIPTORIUM_PORT   port to listen on          (default: 8720)
#   TTS_URL            text service on the GPU box
#   IMAGEGEN_URL       picture service on the GPU box
#   AUTO_START         "1" to start books without a click
#   AUTO_APPROVE       "1" to approve the review step automatically
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Die($m) { Write-Host "`n[x] $m" -ForegroundColor Red; exit 1 }

if ($null -eq (Get-Command 'uv' -ErrorAction SilentlyContinue)) {
    Die "'uv' is not installed. See https://docs.astral.sh/uv/, then run .\scripts\setup.ps1."
}
if (-not (Test-Path (Join-Path $Root 'server\.venv'))) {
    Die "The server isn't set up yet. Run .\scripts\setup.ps1 first."
}

# Default the data dir to a writable, stable folder inside the project so books
# never vanish between restarts. Override by setting $env:SCRIPTORIUM_DATA yourself.
if (-not $env:SCRIPTORIUM_DATA) { $env:SCRIPTORIUM_DATA = Join-Path $Root 'scriptorium-data' }
New-Item -ItemType Directory -Force -Path $env:SCRIPTORIUM_DATA | Out-Null
$Port = if ($env:SCRIPTORIUM_PORT) { $env:SCRIPTORIUM_PORT } else { '8720' }

Write-Host "`n» Starting Scriptorium" -ForegroundColor Magenta
Write-Host "  library:  $($env:SCRIPTORIUM_DATA)"
Write-Host "  reader:   http://localhost:$Port"
Write-Host "  bakery:   http://localhost:$Port/admin"
if ($env:TTS_URL)      { Write-Host "  text:     $($env:TTS_URL)" }      else { Write-Host "  text:     (not set - text steps will wait)" }
if ($env:IMAGEGEN_URL) { Write-Host "  pictures: $($env:IMAGEGEN_URL)" } else { Write-Host "  pictures: (not set - drawing will wait)" }
Write-Host "`n  Press Ctrl-C to stop.`n"

Set-Location (Join-Path $Root 'server')
uv run uvicorn scriptorium.app:app --host 0.0.0.0 --port $Port
