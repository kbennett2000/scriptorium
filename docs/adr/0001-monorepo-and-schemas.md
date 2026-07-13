# ADR 0001: Monorepo with schemas as the single source of truth

- **Status:** Accepted
- **Date:** 2026-07-13

## Context

Scriptorium is a bakery (Python server on the i5) and a reader (React/TypeScript
client), plus an admin UI, that all exchange the same JSON file formats — bundles
and sync documents. If each side hand-maintained its own notion of those formats,
they would drift. See DESIGN §2, §3, §4.

## Decision

We keep one repository with four top-level packages: `server/` (Python 3.12,
FastAPI, uv), `reader/` (Vite + React + TS), `admin-ui/` (Vite + React + TS), and
`shared/`. The JSON Schemas in `shared/schemas/` are the single, normative source
of truth for every bundle and sync file format. TypeScript types are generated
from those schemas with `json-schema-to-typescript` (`shared/gen-types.mjs`) and
consumed by the reader and admin-ui builds; the server validates against the same
schemas via `scriptorium.schemas.validate`.

## Consequences

- Schemas are written before any code that produces or consumes the formats
  (cycle S1), and carry `description` strings as documentation.
- Generated TS types are committed and regenerate deterministically (running the
  generator twice yields no diff), so a schema change that isn't reflected in
  types is visible in review.
- Both languages validate/track the same contract; format drift becomes a schema
  change reviewed in one place.
- `bundle_version` (integer, starts at 1) versions the bundle format for future
  migration.
