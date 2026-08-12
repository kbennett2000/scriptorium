# ADR 0028: single-subject portraits, identity-only conditioning, and a ranked portrait gate

- **Status:** Accepted
- **Date:** 2026-08-12
- **Relates to:** [ADR-0023](0023-character-consistency-ip-adapter.md) (IP-Adapter, primary character
  only), [ADR-0025](0025-portrait-review-gate.md) (the gate),
  [ADR-0026](0026-primary-only-reference-and-prompt-anchoring.md) (primary-only resolution),
  [ADR-0027](0027-alias-contamination-rules.md) (alias publish-filter — extended here),
  DESIGN §7.2, §10. Companion change in `imagegen-service` ADR-0004.

## Context

ADR-0026 and ADR-0027 shipped and did what they claimed: on the re-bake, published aliases fell
**731 → 153**, characters **239 → 200**, and every page plate's prompt carried its era anchor, its
shot framing, the hardened negative, and a correctly resolved **primary** `reference_slug`. The
prompt for plate `0323` named Grushenka's black silk dress, lace fichu and gold brooch explicitly.

The plate still rendered as two men in officers' uniforms.

**Because the reference image was itself two men in officers' uniforms.**
`images/portraits/mitya.png` was not a bust portrait: it was a painting of two young men in blue
uniforms with gold epaulettes, red curtains behind them and a table bearing a red bottle. Every
element that looked wrong across four separate plates was present in that one file. The plates were
faithful re-paintings of their reference.

That portrait anchored **84 plates — 19% of the book, the largest anchor in the cast.**

This was never the model's ceiling. `alyosha.png` and `ivan.png`, from the same model, style and
pipeline, are clean single-figure busts on plain grounds.

Four independent causes, each verified against the published bundle:

| # | Cause | Measured |
|---|---|---|
| 1 | `assemble_portrait` glues `one_line` + `visual_description`, two complete subject noun phrases | **25 of 69** portrait prompts named the subject 2–3 times |
| 2 | IP-Adapter ran `start_at: 0.0` over the whole schedule, `plus-face` fed an uncropped bust | composition, clothing and background transferred with the face |
| 3 | one global unmasked face reference on multi-figure plates | **288 of 440** plates depict 2+ figures |
| 4 | contaminated aliases merged groups *before* descriptors were pooled | `ivan` canonicalised as the monk from Obdorsk — an alias his group had swallowed — then drawn as that monk, anchoring 21 plates |

And a fifth, procedural: the gate (ADR-0025) *was* enabled and *was* approved by a human, but it
presented 69 portraits as a flat unordered grid with nothing to distinguish the one worth 84 plates
from the one worth 7.

## Decision

1. **A portrait prompt names its subject exactly once.** `one_line` is the subject;
   `subject_attributes()` reduces `visual_description` to attribute clauses by stripping a leading
   `A/An/The <modifiers> <person-noun>`, dropping posture/locomotion clauses (which pull a bust out
   to a full scene), and folding later pronoun subjects into attributes (`He wears X` → `wearing X`).
   A new `PORTRAIT_SOLO` constant states the framing that `"bust composition"` alone did not enforce
   — it constrains the crop, not the head count. Portrait plates additionally negative-prompt
   `two people, group portrait, diptych, multiple figures, couple`.
2. **Conditioning transfers identity, not composition.** `imagegen-service` starts IP-Adapter at
   30% of the schedule and head-crops the reference (its ADR-0004). Scriptorium can now override
   both per request.
3. **Multi-figure plates get a weaker, later anchor** (`reference_conditioning`): 0.35 / 0.4 versus
   the service defaults for a solo plate. IP-Adapter has no spatial selectivity, so on a two-person
   plate the second person inherits the anchor's face *and* clothes by construction.
4. **Alias trust is enforced before grouping, not at publication.** ADR-0027's rules now gate
   union-find rule (b) via `_mergeable_alias_norms`. Filtering an alias out of the published list
   cannot undo a merge that already pooled another character's descriptors.
5. **The gate is ranked by cost.** `portrait_anchor_counts` (server-side, using P7's own resolver)
   drives most-anchored-first ordering and a per-card "N pictures" badge.

## Consequences

- **A portrait is not one picture.** It is the reference for every plate its character anchors.
  This ADR treats a portrait defect as costing `anchor_count` plates, and both the negative prompt
  and the gate ordering follow from that.
- **The §10 portrait formula changes.** `assemble_portrait`'s output is no longer
  `portrait_prefix + one_line + ", " + condense(vd)`. Prompt strings are provenance, not published
  page bytes, so **immutability and byte-stability are untouched** — but existing books keep their
  old portraits until re-baked.
- **Rule 3 of ADR-0027 (capitalised-token) now also costs merges, not just aliases.** A book
  typeset entirely in lower case loses alias-driven grouping. Rule (c)'s token containment
  (`"Dmitri"` ⊆ `"Dmitri Fyodorovitch"`) is untouched, so real name variants still group. Accepted
  on the same reasoning as ADR-0027: forgo an uncertain link, never fabricate one.
- **`subject_attributes` is lossy by design.** Posture clauses are dropped even when they carry a
  little appearance detail (`"stands with a fair, long beard"` → the beard survives only via
  `one_line`). An opening it does not recognise is left completely untouched — the pre-ADR
  behaviour, never a silent mangling.
- The face crop degrades gracefully: a host without `PrepImageForClipVision` conditions on the raw
  reference and still renders.

## Not decided here

- **Regional / masked multi-identity conditioning** — the real fix for the 288 multi-figure plates.
  Still ADR-0023 Phase 2; §3 above is a mitigation, not a solution.
- **Merging split characters** (`mitya` / `dmitri` / `dmitri-fyodorovitch` / `karamazov` are four
  entries with four faces for two men). Needs world knowledge; stays the text service's job per
  ADR-0019.
- **Repairing an already-published book.** Not attempted — re-bake instead.
- **An automated single-figure check on a rendered portrait.** Would need a vision model in the
  loop; the ranked gate puts a human on the expensive ones instead.
