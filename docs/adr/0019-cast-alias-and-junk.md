# ADR 0019: cast alias-merging safety and junk filtering (server-side)

- **Status:** Accepted
- **Date:** 2026-08-08
- **Refines:** DESIGN §7.2 (the P2 cast reducer). Pure-function change in
  `server/src/scriptorium/bake/reduce_cast.py`; no schema change.

## Context

Baking *The Brothers Karamazov* (#28054) exposed two cast defects:

1. **One person → many different faces.** Dmitri = Dmitri Fyodorovitch = "Mitya" became three
   separate characters with three unrelated portraits; Alyosha appeared as an old general under his
   formal name. Two mechanisms in the reducer:
   - The single-token subset merge (rule 2c) had no defense against a **shared patronymic/surname**
     token — a bare "Fyodorovitch" is a subset of *both* "Dmitri Fyodorovitch" and "Alexey
     Fyodorovitch", a wrong-merge vector.
   - The same-page **co-occurrence guard** (which correctly keeps two distinct co-occurring names
     apart — the Weena/Eloi rule) *over-fires* on legitimate given-name / full-name variants that
     appear together, splitting one person ("Dmitri" and "Dmitri Fyodorovitch" on the same page).
2. **Junk non-characters.** "me", "peasant", "old-woman", "another-female-figure" all became cast
   entries. The only pre-grouping filter was bare subject pronouns (which omitted "me"), and
   `is_person` never removes a group from the published `cast.json`.

The nickname/diminutive link itself ("Mitya"↔"Dmitri", substring-disjoint) **cannot** be solved by
any in-repo string rule — it needs the external `cast-mentions` transform to emit the diminutive as
an alias. That, plus normalized depicted-vs-cast matching for the P5 warning, is the flagged
follow-up.

## Decision

All changes are in the pure reducer; a **false merge (two people → one) is treated as worse than a
false split**, so every rule is conservative.

- **A1 — junk filtering.**
  - Extend the pre-grouping whole-name stop-word drop from subject pronouns to all
    pronoun/indefinite/demonstrative forms (`_STOP_NAMES`, catches "me"). Only an exact whole-name
    match drops — zero risk to real names.
  - `_drop_junk_groups` (after grouping, **before** the major flag so junk can't claim a
    major/portrait slot) drops a group iff it is on fewer than `_JUNK_MAX_PAGES` (=2, i.e.
    single-page) **and** its display name, after a leading article, has **no capital letter**.
    Capitalization is the reliable signal — real names and role designations are title-cased ("the
    Time Traveller"), junk is lowercase ("peasant"). `is_person` is deliberately not used (a junk
    "peasant" is a person; the non-person collective "the Morlocks" must survive).
- **A2 — patronymic/surname safety (merge-reducing only).** In rule 2c, a lone token contained in
  **≥ 2** distinct full names is ambiguous (shared patronymic/surname) and drives **no** merge. This
  can only *prevent* merges, so it cannot create a false merge.
- **A3 — guard bypass for unambiguous proper containment.** A lone token contained in **exactly one**
  full name that carries **additional** content tokens ("Dmitri" ⊂ "Dmitri Fyodorovitch") is a
  *strong* candidate that merges even across the co-occurrence guard — the union is the same person,
  so it is correct even when the variants co-occur. A mere article variant ("guard" vs "the guard",
  same single content token) is **not** strong, so two co-occurring "Guards" still stay apart.
  `mention_pages` is unioned correctly (the earlier variant is a true earlier mention, ADR-0008
  preserved). Gated by `_CONTAINMENT_OVERRIDES_GUARD` (default on) for a per-book escape hatch.

## Consequences

- **No schema change.** `cast.json` simply carries fewer, better-merged characters
  (`additionalProperties:false`, emitting fewer entries is valid).
- **Spoiler/causality preserved.** The reducer stays pure and post-hoc over already-extracted
  mentions; `mention_pages` (the furthest-read cast-page filter, DESIGN §13) stays accurate; nothing
  enters the text-free selection input.
- **Bounded residual risk.** A2 may, in a rare book, split a real given name that has ≥2 never-merged
  modified full variants (a false split — acceptable). A3 may, in a rare book, merge two different
  co-occurring people who share a given name and where only one full form is present; the flag
  disables it if a specific book regresses.
- **Explicitly deferred to the external text-transform-service** (separate repo): nickname/diminutive
  linking via `cast-mentions` `aliases[]`; a real character-vs-role signal to replace the
  capitalization heuristic; and normalized depicted-vs-cast matching for the P5 "depicted not in
  cast" warning (incl. the optional `present_cast` case/article fold). No in-repo rule can link
  substring-disjoint names, so this is the honest limit of the server-side fix.
