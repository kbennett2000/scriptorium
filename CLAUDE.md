# CLAUDE.md — scriptorium

Illuminated-book pipeline + offline-first reader. Bakery on the i5 server (port 8720) orchestrates GPU work over the LAN (text-transform-service :8712, imagegen-service); readers check out immutable bundles and work fully offline. Monorepo:

- `server/` — Python 3.12, FastAPI, uv (bakery, library, sync, static hosting)
- `reader/` — Vite + React + TS (Capacitor Android/iOS + desktop PWA)
- `admin-ui/` — Vite + React + TS (bake wizard + review gate)
- `shared/schemas/` — JSON Schemas: **the single source of truth for every file format.** Schema change → regenerate TS types → both sides.

## Read before working
1. `system-overview.md` — invariants (§5) are binding
2. `scriptorium-DESIGN.md` — the sections your cycle names
3. `scriptorium-BUILD-PLAN.md` — §0 discipline + your current cycle only

One cycle per session. Plan mode first: restate scope, files, tests, ambiguities. Ambiguity → ask.

## Commands
```
just server-dev / server-test    # uv; tests must pass with NO GPU services running
just reader-dev / admin-dev
just lint-all / test-all
just android-build               # after R5
```

## Hard rules (violating these is a bug even if it works)
- **Fixtures first.** All GPU-service interactions are tested against recorded fixtures in `server/tests/fixtures/tts/`; live calls only behind `-m gpu`.
- **Immutability.** Published page text/structure never changes; revisions are additive; retired plates keep their files. The publish integrity guard is sacred.
- **Byte-stability.** Paginator output is deterministic and byte-exact forever — annotation anchors depend on it. Round-trip tests must stay green.
- **Causality / no spoilers.** Generation for page N sees only pages ≤ N; the selection engine's input type contains no text fields; the reader's cast page filters by furthest-read.
- **Zero-online read path.** No CDN anything; fonts vendored; network calls only in reader `sync/` + `shelf/` (ESLint-enforced — don't weaken the rule).
- **Review gate.** No render before human approval. Don't add bypasses, even for dev (use FakeImagegen instead).
- **GPU sequencing.** Single job worker; TTS unload before any render; `GpuUnavailable` → `waiting_gpu`, never a paid fallback. No API keys in this repo, ever.
- **Never assert exact LLM or image content in tests.** Schema, shape, cross-references only.

## Done means
ruff clean (server) · eslint + tsc clean (reader, admin-ui) · non-gpu tests green · cycle acceptance checklist satisfied · `CYCLE-LOG.md` entry · commits prefixed `S{n}:`/`R{n}:` · schemas and generated types in sync (`git diff --exit-code` after regen).
