# shared — schemas & generated types

The single source of truth for **every file format** in Scriptorium.

- `schemas/` — JSON Schemas for every bundle and sync file. Change a format here, nowhere else.
- `types/` — TypeScript types **generated** from those schemas (committed to the repo).

After editing any schema, regenerate the types so both the server and the web apps agree:

```sh
node gen-types.mjs        # or: just gen-types  (from the repo root)
```

The generator is deterministic — `git diff --exit-code` after regenerating must be clean. The reader
and admin apps also run this automatically before `dev`/`build`. Background:
[ADR-0001](../docs/adr/0001-monorepo-and-schemas.md).
