# ADR 0003: Zero-online read path

- **Status:** Accepted
- **Date:** 2026-07-13

## Context

Read-time must require nothing — no internet, no LAN, no server process (DESIGN
§1 principle 1). Anything the reader fetches at read time is a way for the
offline promise to fail, whether a CDN font, an analytics ping, or an errant API
call. See DESIGN §13.

## Decision

The reading path performs zero network fetches. Specifically:

- No CDN or externally-hosted assets, ever. Fonts (Literata, Inter) are vendored
  into the repo with their OFL license files; no external font loading.
- Model and service versions are pinned into `meta.bake` at publish time so a
  bundle records exactly what produced it, with no runtime lookup.
- All server calls live only in the reader's `sync/` and `shelf/` modules, each
  wrapped in a reachability guard. This boundary is enforced mechanically by an
  ESLint rule that bans `fetch`/HTTP clients outside those two modules (added in
  cycle R1 and wired into `lint-all`).

## Consequences

- A build check asserts the reader's `dist/` contains the vendored woff2 fonts
  and no `fonts.googleapis`/CDN references (cycle R4).
- Introducing a network call in the reading path fails lint, not just review.
- Reader features that need the network (checkout, sync) are structurally
  confined to two modules.
