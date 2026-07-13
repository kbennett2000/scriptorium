# ADR 0008: Causality — no spoilers, structurally

- **Status:** Accepted
- **Date:** 2026-07-13

## Context

Illustrations must never reveal what a reader has not yet read. Enforcing this by
prompt discipline alone is fragile; it should be structural. See DESIGN §1
principle 4, §8, §13.

## Decision

Causality is enforced at three points:

- **Generation** sees only pages ≤ N. Nothing shown for page N is derived from
  pages > N (the scene ledger threads forward only).
- **Selection** consumes scores only — numbers and booleans (`seq`, `page_id`,
  `chapter`, `scene_changed`, `visual_salience`) and no page text. This is made
  structural: the selection input type contains no text fields. Lookahead over
  scores is allowed; content lookahead is impossible because content never enters.
- **The reader's cast/dramatis-personae page** shows only characters whose
  `mention_pages` include a page ≤ the reader's furthest-read position.

## Consequences

- The selection engine (cycle S7) takes a dataclass with no text; a test asserts
  the reader cast filter hides a character first mentioned beyond furthest-read.
- Spoiler-freedom does not depend on anyone remembering to avoid spoilers.
