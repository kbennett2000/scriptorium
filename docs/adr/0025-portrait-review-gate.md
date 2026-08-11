# ADR 0025: optional portrait-review gate (approve portraits before the book draws)

- **Status:** Accepted
- **Date:** 2026-08-11
- **Relates to:** [ADR-0023](0023-character-consistency-portrait-reference.md) (portraits seed pages via
  IP-Adapter), [ADR-0015](0015-auto-approve.md) (auto-approve), [ADR-0020](0020-auto-start.md)
  (unattended), DESIGN §7.3 (state machine), §10 (render), §11.1 (review gate).

## Context

Every character portrait already seeds the book's illustrations — a portrait PNG is fed into each
page plate as an IP-Adapter reference (ADR-0023). But portraits render *inside* the single post-
approval render pass, so a wrong-looking portrait (wrong age, gender, identity) silently seeds
hundreds of pages before anyone can see it. The owner wanted an **optional stop**: read the book →
render every portrait → **pause** → look at each portrait next to the prompt that drew it, tweak the
prompt or the character's description, and regenerate individual portraits until happy → then draw
the rest of the book from the approved portraits.

## Decision

Split the render into **portraits first → optional stop → pages**, gated by a new per-book bake flag.

**New states** (job.py `_CHAIN`, between `approved` and `rendering`):
`portraits_rendering` (GPU) → `portraits_review` (resting). `PORTRAITS_RENDERING` is a `GPU_STATE`;
the transition table derives the new edges automatically.

**New phases** (p7_render.py) — the old single `Render` becomes two, sharing an `_ImagegenPhase`
base (client injection + the `__unload__` GPU-handoff unit):
- `PortraitRenderEnter`: `approved → portraits_rendering` (CPU, 0 units).
- `PortraitRender`: `portraits_rendering → portraits_review`; renders only `portrait-*` plates.
- `Render`: `rendering → rendered`; renders the cover + page plates (portraits already on disk;
  existence-based `unit_done` skips them, so no double-render).

**Gate decision** (runner.py, the same resting-state branch AUTO_APPROVE uses): at
`portraits_review`, if the per-book `bake_config.portrait_review` flag is set the job **rests** for a
human; otherwise the runner **auto-advances** `portraits_review → rendering` in the same tick. Keyed
on the per-book flag (not global `auto_approve`), so the gate stops even in the unattended overnight
flow — the flag deliberately overrides "unattended" for this one stop.

**Reused review machinery** (review_api.py) — most of it already understood `portrait-{slug}` ids:
- `edit_prompt` / `edit_cast` allowed at `portraits_review` (the "edit prompt" and "edit description"
  levers). A description edit re-derives the portrait prompt (`rederive_portrait_prompt`,
  p5_prompts.py) so a subsequent regenerate reflects it — while a manual prompt override still wins.
- `regen_plate` allowed at `portraits_review` (regenerate one portrait, fresh seed, overwrite in
  place — pre-publish, no immutability concern).
- `plate_image` serves `images/portraits/{slug}.png` for `portrait-*` ids.
- New `POST /books/{id}/approve-portraits` → `approve_portraits` advances `portraits_review →
  rendering`.

**UI** (admin-ui): a "pause to review portraits" toggle on the new-book wizard; a `PortraitReview`
screen (image + editable prompt + editable description + per-portrait regenerate + "approve & draw
the book"); a state-gated nav button and the two new states in the progress chain.

## Why this keeps the invariants

- **Byte-stability / immutability:** identical prompts, deterministic `_default_seed`, identical
  render call — only phase boundaries move. Toggle-off output is byte-identical to before (the
  offline P0→P8 golden bundle tests pass unchanged). Portrait regen overwrites the *work-tree* PNG
  pre-publish (already allowed); no published bytes ever mutate, so the publish integrity guard is
  untouched. Page text is never touched.
- **Causality / review gate:** the stop is *after* approval and *before* page render; it adds a gate,
  never a bypass. Pages still seed from the approved portraits via `_portrait_reference`.
- **GPU sequencing:** `PortraitRender` keeps the leading `__unload__` (TTS-unload + imagegen health;
  `GpuUnavailable → waiting_gpu`).

## Scope / limits

- No negative-prompt editing (no endpoint today; the subject prompt + description are the levers).
- Multi-character-per-frame identity stays deferred (ADR-0023 Phase 2).
- The flag lives in `bake_config` only, not published `meta` — it is a bake-time control, not a bundle
  property, keeping the immutability surface minimal.
