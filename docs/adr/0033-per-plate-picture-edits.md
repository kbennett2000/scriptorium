# ADR 0033: per-plate picture edits (private, post-publish)

- **Status:** Accepted
- **Date:** 2026-08-13
- **Relates to:** ADR-0002 (bundle immutability), ADR-0014 (private art sets),
  ADR-0011 (imagegen API), ADR-0023/0028 (reference conditioning), DESIGN §8, §13.

## Context

A reader sometimes dislikes **one** illustration in a finished book — a face, a composition, a
misread scene. Art sets (ADR-0014) can re-illustrate the *whole* book in a new style or re-roll, but
there is no way to fix a *single* plate, keep its neighbours, feed the current image back in as a
starting point, or change its caption. Captions, moreover, are not stored data at all: the reader
derives each one at read time from the page's `ledger.best_visual_beat`, frozen inside the immutable
`pages/*.json`.

The product owner wants an **Edit** affordance on a picture in the reader that opens a screen like the
imagegen dev harness: the prompt that made the image is pre-filled, the current image is loaded as the
img2img **starting image**, the reader generates alternatives until satisfied, then **replaces** that
plate and edits its caption — **for that household profile only**, never for everyone.

## Decision

**A private, per-plate "edits" overlay, on the art-set channel.** Each profile gets a reserved
singleton overlay per book at `artsets/{user}/{book}/edits/` — outside `library/`, exactly like a
set, so the publish integrity guard and the frozen `pages/*.json` are never touched. It holds only
the edited plates, at the **same relative paths as the bundle** (`images/web/plates/{plate_id}.webp`,
…), a `manifest.json`, and `edits.json` (the new `artset-edits` schema): a `plate_id → {caption,
prompt, seed, denoise, created}` map plus `source_revision`. It is **not** a `set.json`, so it never
appears in the Pictures menu; the reader **layers** it over whatever reader is active (the original
bundle or an active style set), overriding image *and* caption per edited plate.

**img2img is a client parameter, not a new pipeline.** imagegen-service already accepts `initImage` +
`denoise`; `ImagegenClient.txt2img` gains `init_image`/`denoise` (forwarded only when set, so every
existing txt2img request stays byte-identical). The current plate image is the starting image, so the
book's look carries over without re-wrapping style or re-deriving character references (a possible
later refinement).

**Generation is synchronous and online; the result is then resident.** Three endpoints under the
overlay (`…/edits/{plate_id}/context|candidate|commit`) pre-fill, generate a scratch candidate, and
commit the chosen one. Commit runs `make_derivatives` and rebuilds the overlay manifest (with
`edits.json` marked reader-required so captions reach the device). The reader then checks the overlay
out via the existing `artsetCheckout`, so the replacement shows **offline** thereafter. All network
lives in the reader's `shelf/` boundary (zero-online read path preserved); `GpuUnavailable` → HTTP
503 (retryable), never a fallback (GPU-sequencing rule preserved).

## Consequences

- A single plate can be fixed privately without a whole-book re-roll; captions become editable for the
  first time, through an additive channel rather than by touching frozen page docs.
- The overlay overwrites its own plate in place (private; no `-rN` history needed). `source_revision`
  records the book revision the edit derived from so a later household re-publish is *detectable* (the
  edit is not auto-invalidated).
- First cut scopes to **page plates**; cover/portrait editing, style/character-reference reinforcement
  on the img2img pass, and art-set-switch reconciliation are follow-ups.
- The overlay is served under the reserved literal set id `edits` (the serving guard accepts it
  alongside `set-…`); a literal id cannot traverse and the existing `.resolve()` guard still applies.
