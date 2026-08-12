# reader — the offline-first reading app

Vite + React + TypeScript. Readers pick a profile, download a finished book once, and then read it
**fully offline** — pages, illustrations, cast page, search, highlights. The reading path makes zero
network calls; only the shelf/sync layer talks to the home server. The same app is wrapped as an
Android app via Capacitor.

```sh
npm install
npm run dev            # http://localhost:5173 (proxies /api to the server on :8720)
npm run build          # -> dist/ (served by the server at /)
npm run lint && npm run typecheck
npm run test           # Vitest
```

- **Reading it as a person:** [docs/guide/reading-books.md](../docs/guide/reading-books.md).
- **Building the phone app:** [BUILDING.md](BUILDING.md).
- The "zero-online read path" is enforced (vendored fonts, no CDN) — see
  [ADR-0003](../docs/adr/0003-zero-online-read-path.md); `npm run build:check` guards it.
