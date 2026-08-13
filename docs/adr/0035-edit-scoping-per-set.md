# ADR 0035: private per-plate edits are scoped to the picture set they were made on

- **Status:** Accepted
- **Date:** 2026-08-13
- **Relates to:** ADR-0033 (per-plate picture edits), ADR-0034 (edit fidelity + harness parity),
  ADR-0014 (per-user art sets), DESIGN §8.

## Context

The post-publish picture editor (ADR-0033/0034) writes each replacement into a private overlay at
`artsets/{user}/{book}/edits/`, keyed by `plate_id`, and the reader layers that overlay on top of
**whatever set is active** (base book or a style set). ADR-0034 made an edit *reproduce* the active
reader's look, but the overlay itself was still **book-global**: one image per `plate_id`, applied to
every set.

That produced a confusing bug. A reader with all three plates edited (on the Comic Book set) switched
to a Cyberpunk set and saw **no change** — the set reader underneath swapped correctly, but the
overlay served the comic edits for every plate on top. "Selecting a new picture set has no effect."
The edits also recorded no set of origin (`set_id` was absent), so they couldn't be attributed to a
reader even in principle.

## Decision

**A private edit is scoped to the reader it was made from.** An edit is identified by
`(scope, plate_id)`, where `scope` is `"default"` (the base book) or a `"set-…"` style-set id.
Switching sets shows that set's own picture unless it, too, has been edited.

- **Schema.** `artset-edits` `plates[plate_id]` becomes a `{ scope → entry }` map (was a single
  entry). The entry gains an optional `set_id` so it is self-describing. The base book edits under
  scope `"default"`; a style set edits under its own id — so the same plate can carry a distinct edit
  per set.
- **Storage.** The overlay image for an edit lives under a scope segment,
  `images/{web,thumbs,plates}/plates/{scope}/{plate_id}.…`, so a base-book edit and a comic-set edit
  of the same plate coexist as separate files. The `reader_required` globs (`images/web/**`,
  `images/thumbs/**`) already match the nested path; the archival `images/plates/**` stays excluded.
- **Server.** `plate_context`, `_current_caption` and `_current_plate_png` resolve the prior edit for
  the **active scope only** (so a re-edit chains from the last result on that reader, and the img2img
  starting image is that scope's plate). `generate_candidate` records the scope in the candidate
  sidecar; `commit_edit` writes the nested entry and the scoped image.
- **Reader.** `OverlayImageBundleReader` is built for the active scope and surfaces only edits filed
  under it — it maps a requested plate path to `…/plates/{scope}/{plate_id}.webp` and delegates to the
  wrapped set/base reader when there is no edit for that scope. So an edit made on the comic set
  overrides the comic set; switch to Cyberpunk and its own picture shows through.

**Legacy edits (pre-ADR-0035).** A flat entry recorded no scope, so it cannot be attributed to a
reader. The reader **ignores** flat entries (they stop masking immediately — the whole point of the
fix), and the server **drops** them from `edits.json` on the next commit (a one-time migration so a
mixed file still validates). On-disk files are left in place — no destructive delete.

## Consequences

- Switching picture sets now changes the pictures, even for a plate the reader has edited on another
  set — the reported bug is fixed.
- A reader can maintain different per-plate edits per set (a fix that only makes sense in the comic
  look need not follow them into the cyberpunk look), at the cost of one overlay image per (scope,
  plate) instead of per plate.
- The three throwaway comic-set edits made before this change become inert under the new reader and
  are cleared from `edits.json` the next time any plate is committed.
- Still scoped to page plates (cover/portrait editing remains a follow-up). Delivery is unchanged:
  writes stay in the private `edits/` overlay, checked out via `artsetCheckout`, shown offline; all
  network stays in the reader's `shelf/` boundary and `GpuUnavailable → 503`, never a fallback.
