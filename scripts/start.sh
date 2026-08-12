#!/usr/bin/env bash
# Start the Scriptorium bakery server (macOS / Linux).
# Serves the reader at / and the admin app at /admin on port 8720.
# Run scripts/setup.sh first. Windows: use scripts\start.ps1.
#
# Honors these environment variables if you set them (all optional):
#   SCRIPTORIUM_DATA   where your library lives   (default: ./scriptorium-data)
#   SCRIPTORIUM_PORT   port to listen on          (default: 8720)
#   TTS_URL            text service on the GPU box
#   IMAGEGEN_URL       picture service on the GPU box
#   AUTO_START         "1" to start books without a click
#   AUTO_APPROVE       "1" to approve the review step automatically
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

die() { printf '\n\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

command -v uv >/dev/null 2>&1 || die "'uv' is not installed. See https://docs.astral.sh/uv/, then run ./scripts/setup.sh."
[ -d "$ROOT/server/.venv" ] || die "The server isn't set up yet. Run ./scripts/setup.sh first."

# Default the data dir to a writable, stable folder inside the project so books
# never vanish between restarts. Override by exporting SCRIPTORIUM_DATA yourself.
export SCRIPTORIUM_DATA="${SCRIPTORIUM_DATA:-$ROOT/scriptorium-data}"
mkdir -p "$SCRIPTORIUM_DATA"
PORT="${SCRIPTORIUM_PORT:-8720}"

printf '\n\033[1;35m» Starting Scriptorium\033[0m\n'
printf '  library:  %s\n' "$SCRIPTORIUM_DATA"
printf '  reader:   http://localhost:%s\n' "$PORT"
printf '  bakery:   http://localhost:%s/admin\n' "$PORT"
[ -n "${TTS_URL:-}" ]      && printf '  text:     %s\n' "$TTS_URL"      || printf '  text:     (not set — text steps will wait)\n'
[ -n "${IMAGEGEN_URL:-}" ] && printf '  pictures: %s\n' "$IMAGEGEN_URL" || printf '  pictures: (not set — drawing will wait)\n'
printf '\n  Press Ctrl-C to stop.\n\n'

cd "$ROOT/server"
exec uv run uvicorn scriptorium.app:app --host 0.0.0.0 --port "$PORT"
