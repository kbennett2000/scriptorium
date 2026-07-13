# Scriptorium

Turns books into illuminated, offline-readable bundles: a **bakery** (batch
pipeline on the i5 server, GPU work delegated over the LAN) and a **reader**
(Capacitor/PWA client that owns books entirely on-device after checkout).

See [`scriptorium-DESIGN.md`](scriptorium-DESIGN.md) for the full design and
[`scriptorium-BUILD-PLAN.md`](scriptorium-BUILD-PLAN.md) for the cycle plan.

## Layout

| Path | What |
|---|---|
| `shared/schemas/` | JSON Schemas — the single source of truth for every bundle/sync file |
| `shared/types/` | TypeScript types generated from the schemas (committed; run `node shared/gen-types.mjs`) |
| `server/` | Python 3.12 / FastAPI bakery orchestrator, library, sync, admin API (uv) |
| `reader/` | Vite + React + TS offline-first reader client |
| `admin-ui/` | Vite + React + TS admin workbench (served at `/admin`) |
| `docs/adr/` | Architecture Decision Records |
| `data/styles.json` | Seed illustration styles (copied into `SCRIPTORIUM_DATA` at runtime) |

## Development

Requires [`uv`](https://docs.astral.sh/uv/), Node 20+, and
[`just`](https://github.com/casey/just).

```sh
# server
cd server && uv sync
just server-test        # or: cd server && uv run pytest
just server-dev

# clients
cd reader && npm install     # and/or: cd admin-ui && npm install
just reader-dev
just admin-dev

# whole repo
just lint-all
just test-all
```

## Status

Early build. Cycle S1 (scaffold + schemas + ADRs) complete; see `HANDOFF.md` and
`CYCLE-LOG.md`.
