# ADR 0023: character consistency via portrait image-reference (IP-Adapter)

- **Status:** Accepted (pipeline half landed; imagegen-service + ComfyUI half in progress)
- **Date:** 2026-08-11
- **Relates to:** [ADR-0011](0011-imagegen-api.md) (imagegen API), DESIGN §10 (render).

## Context

After the text-side fixes, illustration *prompts* correctly name and describe each character (e.g.
"Mitya, young officer in frock-coat"), but the image model renders them inconsistently — a described
young officer comes out as an old monk on one page and a woman on another. SDXL text-to-image has no
memory of what a character looks like between plates. The bake already renders one canonical
**portrait** per major character (`images/portraits/{slug}.png`); nothing fed it back into the page
plates.

## Decision

Feed a depicted character's portrait into their page plates as an **image reference** (IP-Adapter),
so the rendered figure resembles the same person everywhere.

**Pipeline half (this repo):**
- `ImagegenClient.txt2img` gains an optional `references: list[bytes] | None = None` (mirroring the
  `style`-only-when-set pattern): forwarded to the service as base64 only when set, folded into
  `FakeImagegen`'s digest only when set — so the `references=None` path is byte-identical and every
  existing determinism/round-trip fixture stays valid.
- `p7_render.render_plate` computes the reference for a **page plate** via `_portrait_reference`:
  read `derived.depicted`, resolve the first label that maps (by name/alias) to a cast character
  whose portrait PNG exists, and pass that PNG's bytes. Cover/portrait pseudo-plates and plates whose
  characters have no portrait pass nothing (prompt-only, unchanged).
- **Render order:** `Render.units` now renders all `portrait-*` plates **before** page plates, since a
  page plate depends on its characters' portraits existing. `unit_done` keeps this resumable.

**Service half (imagegen-service + ComfyUI, separate work):** `/generate` accepts `references`
(base64), uploads them to ComfyUI, and switches to an IP-Adapter SDXL workflow
(`ComfyUI_IPAdapter_plus` + `ip-adapter-plus_sdxl_vit-h` + CLIP-ViT-H). Absent → today's txt2img.

## Scope / limits

- **Primary character only.** Phase 1 conditions on the single most-prominent depicted character.
  Multiple identities in one frame (regional IP-Adapter) is deferred (Phase 2) — genuinely harder.
- **Better, not perfect.** SDXL identity on stylized painterly scenes across hundreds of varied
  compositions still misses; quality is judged by a human re-bake, never asserted in tests (CLAUDE.md).

## Why this keeps the invariants

- **Byte-stability / immutability:** the `references=None` path is byte-identical; only plates that
  actually receive a reference change, and only on a fresh (re)bake — no published page bytes mutate.
- **GPU sequencing / review gate:** unchanged — references are computed inside the existing P7 render
  unit, after the `__unload__` gate and after approval.
- **Determinism:** references derive from on-disk portraits + the deterministic per-plate seed, so a
  re-render of an unchanged tree reproduces bytes.
