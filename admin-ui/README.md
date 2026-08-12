# admin-ui — the bakery workbench

Vite + React + TypeScript. The owner's control room: make a new book (the bake wizard), watch it
progress, review the plan before any pictures are drawn (the review gate), optionally review
character portraits, and publish. Served by the server at **`/admin`**.

```sh
npm install
npm run dev            # http://localhost:5174 (proxies /api to the server on :8720)
npm run build          # -> dist/ (served by the server at /admin)
npm run lint && npm run typecheck
npm run test           # Vitest
```

Using it, step by step: **[docs/guide/making-books.md](../docs/guide/making-books.md)**.
