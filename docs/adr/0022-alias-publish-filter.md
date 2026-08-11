# ADR 0022: alias publish-filter — drop pronouns and cross-character names from cast.json

- **Status:** Accepted
- **Date:** 2026-08-11
- **Extends:** [ADR-0019](0019-cast-alias-and-junk.md) (cast alias + junk handling).

## Context

Published illustrations put the wrong character in the frame: Marfa Ignatyevna (a woman) was drawn
with Grigory's appearance ("an old man with grey beard reading Lives of the Saints"); Dmitri
("Mitya," an adult) was drawn as a boy. Tracing the pipeline:

1. The external `cast-mentions` transform emits, inside one character's `aliases[]`, junk that isn't
   an alias of that character — bare pronouns ("he", "his", the archaic "Thou"), and the **proper
   names of other characters** ("Grigory", "Nikolay Parfenovitch", "Ivan" all appeared under
   "Mitya").
2. `reduce_cast._build_one_group` republished those aliases into `cast.json` **verbatim** — the
   existing `_STOP_NAMES` pronoun filter was applied only to a mention's *name* (`_collect_records`),
   never to its aliases.
3. `present_cast` (`p5_prompts.py`) marks a character "present" on a page if its name *or any alias*
   appears in the page ledger's `present[]`. A contaminated alias therefore drags the wrong
   character into a scene, and the external `illustration-prompt` LLM then binds that character's
   appearance/age/gender to the wrong name.

ADR-0019 correctly defers alias *linking* (e.g. recognizing "Mitya" ≡ "Dmitri") to the external
service — no in-repo rule can link substring-disjoint names. But *filtering* obvious contamination is
in-repo, and its absence was a real defect.

## Decision

Add `_filter_published_aliases(groups)`, run in `reduce_cast` after junk-drop and before majors are
marked. For each group it drops an alias whose normalized form is:

- in `_STOP_NAMES` (pronouns/demonstratives — now also including the archaic "thou/thee/thy/thine/ye"
  and the possessive "his", which 19th-c. translations surface), or
- the canonical name of a **different** group (cross-character contamination).

`_STOP_NAMES` gains the archaic/possessive pronouns so the filter catches them in both the existing
name-drop and the new alias-drop.

## Why this is safe

- **Filter, never link.** It only *removes* aliases; it never merges groups or invents a link. The
  deferred diminutive-linking problem (ADR-0019) is untouched. Dropping a cross-name alias at worst
  forgoes an uncertain link; it never fabricates a false one — the conservative direction.
- **No new dependency on LLM content.** Purely structural: normalized-string membership against the
  set of group names. Tests assert grouping/aliases only, never model wording (CLAUDE.md).
- **Immutability / byte-stability untouched.** `reduce_cast` is a work-tree step; this changes only
  freshly-produced `cast.json`, not any published page bytes or the paginator.

## Consequences

- `cast.json` no longer lists pronouns or other characters' names under a character's aliases, so
  `present_cast` stops cross-linking characters into scenes they aren't in — the dominant in-repo
  cause of wrong-identity illustrations.
- Residual mis-attribution the *illustration-prompt* LLM itself makes (reading a page's prose and
  binding the wrong appearance) is out of scope here and addressed upstream in the
  text-transform-service (transform template + validators).
- Verified on the real `pg-28054` mentions: "Mitya" no longer carries "Nikolay Parfenovitch" / "Ivan"
  / "Alyosha" / pronouns; a Marfa-only page no longer pulls in Grigory.
