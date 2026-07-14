#!/usr/bin/env bash
# R1b offline-acceptance harness (DESIGN §13 milestone). Seeds the committed fixture bundle into a
# throwaway library, starts the real server, and prints the ~2-minute human walk. The point is to
# prove the reading path works fully offline: after Download → Resident, the server can die and the
# book still opens, navigates, shows plates, and restores position on reload — with ZERO network
# requests while reading.
#
# Usage:  reader/scripts/offline-acceptance.sh
# Ctrl-C stops the server; the temp data dir is left for inspection and printed at exit.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE="$REPO_ROOT/server/tests/fixtures/bundle"
BOOK_ID="usr-ce8f5ebd29d0"
PORT="${SCRIPTORIUM_PORT:-8720}"

DATA_DIR="$(mktemp -d -t scriptorium-r1b-XXXXXX)"
cleanup() {
  echo
  echo "Server stopped. Temp data dir left for inspection: $DATA_DIR"
}
trap cleanup EXIT

echo "Seeding fixture bundle '$BOOK_ID' into $DATA_DIR/library/ …"
mkdir -p "$DATA_DIR/library/$BOOK_ID"
cp -R "$FIXTURE/." "$DATA_DIR/library/$BOOK_ID/"

cat <<WALK

════════════════════════════════════════════════════════════════════════
  R1b OFFLINE ACCEPTANCE — the 2-minute human walk
════════════════════════════════════════════════════════════════════════
  Server about to start on http://localhost:$PORT (data: $DATA_DIR).

  In a SECOND terminal:
      cd reader && VITE_SERVER_URL=http://localhost:$PORT npm run dev
  Open the printed dev URL (http://localhost:5173) in a browser, then:

    1. Shelf lists "The Winter Quay". Click Download → it becomes Resident.
    2. Open DevTools ▸ Network, click "Preserve log", and clear it.
    3. STOP THE SERVER: return here and press Ctrl-C.
    4. In the browser, click Open. Read: page-turn with the buttons / arrow
       keys / swipe across page 1 → 6 (page 1 shows the chapter title
       "The Winter Quay" and a plate; page 6 shows a plate too).
    5. Tap a plate → lightbox opens; click image to zoom; Esc/backdrop closes.
    6. Scroll partway down a page, then RELOAD the tab (Cmd/Ctrl-R).
       ✔ It reopens the same book at your position (Continue).
       ✔ "storage protected: yes/no" is visible (bottom-right).
       ✔ Network tab shows ZERO requests during steps 4–6.

  Record: pass/fail per checkmark + a screenshot of the reading view and the
  idle Network tab → paste into CYCLE-LOG.md.
════════════════════════════════════════════════════════════════════════

WALK

echo "Starting server (Ctrl-C to stop)…"
cd "$REPO_ROOT/server"
SCRIPTORIUM_DATA="$DATA_DIR" exec uv run uvicorn scriptorium.app:app --host 0.0.0.0 --port "$PORT"
