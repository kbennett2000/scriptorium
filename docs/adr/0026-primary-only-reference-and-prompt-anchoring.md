# ADR 0026: primary-only portrait reference, period anchoring, and composition control

- **Status:** Accepted
- **Date:** 2026-08-12
- **Relates to:** [ADR-0023](0023-character-consistency-portrait-reference.md) (portrait
  image-reference), [ADR-0014](0014-private-art-sets.md) (picture sets),
  [ADR-0019](0019-cast-alias-and-junk.md) / [ADR-0022](0022-alias-publish-filter.md) (cast alias
  hygiene), [ADR-0011](0011-imagegen-api.md) (imagegen API), DESIGN §9 (styles), §10 (render).

## Context

A review of the published *Brothers Karamazov* (458 plates, `oil-painting`) found plates that
contradict their own caption. Two are diagnostic:

- *"The woman kneels before Elder Zossima on the portico step…"* rendered as **two East Asian
  Buddhist-looking monks**, with no woman in the frame.
- *"Pyotr Ilyitch sits while Madame Hohlakov shrieks…"* rendered as **two young women**, with no
  Pyotr Ilyitch.

The obvious hypothesis — "a local SDXL model simply can't do this" — is not what the data shows.
Measured over all 458 plates of that book:

| | |
|---|---|
| Plates asking for 3–4 figures | 180 (39%) |
| Plates asking for 2+ figures | 358 (78%); only 16 (3.5%) single-figure |
| `derived.shot` reaching the prompt | **2 / 458** |
| `era` ("Russia 1870s") reaching the prompt | **32 / 458**, only when the transform volunteered it |
| Plates warning "depicted not in cast" | 198 |
| Page plates anchored on a **non-primary** character | 10 |

Three distinct defects, all in this repo:

1. **`_portrait_reference` violated its own ADR.** ADR-0023 specifies "primary character only", but
   the implementation looped over `derived.depicted` and took *the first label that happened to
   resolve **and** have a portrait on disk*. So whenever the real subject was a minor (no portrait)
   or the transform over-qualified their name, a **secondary** character's face silently became the
   whole plate's identity anchor. Plate 0033 (`["Nastasya", "the elder"]`, Nastasya being a minor)
   fell through to the elder's monk portrait. Plate 0345 (`["Pyotr Ilyitch Karamazov", "Madame
   Hohlakov"]` — a name the transform invented) fell through to Madame Hohlakov. Both symptoms are
   exactly "the anchor character, duplicated, and the real subject missing".
2. **No period anchor reached the image model.** `era` was passed only to the *text* transforms and
   written into `meta.json`. With no period cue, SDXL falls back to its own priors: a Russian
   Orthodox "monk in a red coarse coat" is rendered as a Buddhist one. The symptom had previously
   been patched by bolting anti-anachronism terms onto `oil-painting`'s negative alone.
3. **Composition was computed and discarded.** The transform has always emitted `derived.shot`
   (`close`/`medium`/`wide`); P7 never read it. The M1 retro already recorded the consequence —
   person-centric beats render as landscapes with a speck — and noted that an identity reference
   cannot express itself on a 40-pixel face, which is plausibly *why* ADR-0023 never visibly helped.

Two paths also dropped references entirely: a picture set (ADR-0014) rendered **prompt-only**, and
`regen_published_plate` re-rendered a plate without the anchor it originally had.

## Decision

**1. Primary-only reference, literally.** `portrait_reference(depicted, characters, portraits_dir)`
resolves **`depicted[0]` and nothing else**. If it does not resolve, or resolves to a character with
no portrait, the plate renders prompt-only. Never borrow another character's face.

**2. Resolve labels properly.** `build_cast_index` / `resolve_character` match a depicted label
against every cast name and alias by: exact fold → article/honorific-stripped fold ("The Elder",
"Madame Hohlakov", "Father Zossima") → token-subset, most-specific-wins ("Pyotr Ilyitch Karamazov"
→ `pyotr-ilyitch`). A key claimed by two characters is **ambiguous and resolves to nothing** — the
cast reducer can still leave a shared alias (ADR-0019/0022), and guessing a face is worse than none.

**3. Record what anchored the plate.** `render.reference_slug` (nullable, optional) is added to
`prompt.schema.json`, so a mis-anchored plate is findable without eyeballing the art.

**4. Anchor the period.** `wrap_prompt` gains an `era` argument and emits
`style.prefix + [era, ] + subject + [, shot] + style.suffix`. P7 passes `job.bake_config["era"]`; a
picture set reads `era` from the published `meta.json`, since a set job's `bake_config` carries only
`style_id`.

**5. Use the shot.** `derived.shot` maps to composition language (`close` → "close-up, head and
shoulders, the figure fills the frame"; `medium` → "medium shot, figures large in the frame, waist
up"; `wide` → "wide establishing shot"). An unknown or missing shot contributes nothing.

**6. One global negative for every style.** `_GLOBAL_NEGATIVE` appends SDXL's stock failure modes —
`duplicate, cloned face, two heads, extra limbs, extra fingers, deformed, mutated, bad anatomy,
disfigured, crowd, extra people` — plus the anti-anachronism terms that were previously special-cased
on `oil-painting`. Terms already present in a style's own negative are de-duplicated, so the string
stays readable. The subject's trailing full stop is dropped so the style suffix reads as a
continuation rather than `"…killed her father., canvas texture"`.

**7. Feed references on every render path.** Picture sets now render **portraits first** (mirroring
P7's phase split) and condition page plates on *that set's own* portraits;
`regen_published_plate` re-conditions on the book's portraits.

## Consequences

- The two diagnostic plates can no longer happen: an unresolvable or portrait-less primary yields a
  prompt-only render instead of a wrong face duplicated across the frame.
- **Prompt strings change.** `wrapped_prompt` / `negative_prompt` differ for any *new* render. This
  is a prompt-provenance change, not a paginator change — the byte-stability invariant (annotation
  anchors) is untouched, and published pixels are never mutated: new art lands in `artsets/…` or as
  an additive `-rN`.
- A picture set is now a genuine re-illustration *with* character consistency, and it picks up
  every wrap-time improvement above **without an LLM re-run** — which makes an existing published
  book the cheapest way to evaluate a prompt change.
- Set unit order changed (portraits first). `unit_done` is artifact-based, so resuming an
  interrupted set is unaffected.
- Fewer plates get a reference at all (no more false anchors). That is the point: ADR-0023's
  "primary character only" is now honest, and multi-identity conditioning stays deferred to its
  Phase 2.

## Not decided here

- **Figure count.** "One scene, ≤2 figures" belongs to the `illustration-prompt` transform in
  `text-transform-service`; 39% of plates asking for 3–4 figures is the single largest remaining
  cause and is fixed in that repo's companion cycle.
- **Cast merge quality.** The `elder` entry has swallowed `Father Ferapont`, `Zossima` and `Nastya`
  as aliases, and there are near-duplicate `Pyotr Ilyitch` entries. ADR-0022's filter was meant to
  catch this. Separate root cause in `reduce_cast.py`; the ambiguity rule above limits the blast
  radius meanwhile.
- **steps / cfg / sampler.** The imagegen service exposes none (ADR-0011); `styles.json.params`
  remains dead config.
