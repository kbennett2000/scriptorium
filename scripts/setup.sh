#!/usr/bin/env bash
# Scriptorium one-time setup (macOS / Linux).
# Checks your tools, installs the server, and builds the two web apps so a single
# server can serve both. Safe to re-run. Windows: use scripts\setup.ps1.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say()  { printf '\n\033[1;35m» %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
die()  { printf '\n\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

say "Checking your tools"
have uv   || die "'uv' is not installed. Get it at https://docs.astral.sh/uv/ then run this again."
ok "uv"
have node || die "'node' (Node.js 20+) is not installed. Get it at https://nodejs.org then run this again."
ok "node $(node --version)"
have npm  || die "'npm' is missing (it comes with Node.js). Reinstall Node from https://nodejs.org."
ok "npm"

say "Installing the server (uv sync)"
( cd server && uv sync )
ok "server dependencies ready"

say "Building the reader app"
( cd reader && npm install && npm run build )
ok "reader built (reader/dist)"

say "Building the admin app"
( cd admin-ui && npm install && npm run build )
ok "admin built (admin-ui/dist)"

DATA_DIR="${SCRIPTORIUM_DATA:-$ROOT/scriptorium-data}"
mkdir -p "$DATA_DIR"
ok "library folder ready at $DATA_DIR"

say "All set!"
printf "Next, start the server with:\n\n    ./scripts/start.sh\n\nThen open http://localhost:8720 (reader) and http://localhost:8720/admin (bakery).\n\n"
