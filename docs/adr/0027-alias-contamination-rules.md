# ADR 0027: three more alias-contamination rules (shared, title-stripped, not-a-name)

- **Status:** Accepted
- **Date:** 2026-08-12
- **Relates to:** [ADR-0022](0022-alias-publish-filter.md) (alias publish-filter — extended here),
  [ADR-0019](0019-cast-alias-and-junk.md) (alias safety + junk filtering),
  [ADR-0026](0026-primary-only-reference-and-prompt-anchoring.md) (primary-only reference),
  DESIGN §7.2 (cast reduction).

## Context

ADR-0026 made a plate's portrait reference resolve from `depicted[0]` only, and refuse ambiguous
labels. That surfaced how bad the underlying cast data is. On the published *Brothers Karamazov*
(239 characters, **731 published aliases**):

| Class | Count | Example |
|---|---|---|
| Alias claimed by 2+ characters | 159 | `"the old man"` → **nine** characters; `"Dmitri Fyodorovitch"` → six |
| Alias with no capitalised token | 487 | `"the boy"`, `"brother"`, `"mamma"`, `"sir"`, `"bravo!"`, `"the shop"` |
| Alias equal to another character's name once titles are stripped | 12 | group `elder` claims `"Zossima"`; the other group is named `"Father Zossima"` |

ADR-0022's filter caught **none** of these: it drops pronouns and aliases equal to another group's
**verbatim** canonical name, and `"Zossima" != "Father Zossima"`, `"the old man"` is nobody's
canonical name, and `"the boy"` is not a pronoun.

The damage is not cosmetic. Contaminated aliases feed `present_cast`, so the illustration transform
is told the wrong characters are in the scene and weaves in the wrong appearance — the exact failure
ADR-0022 was written to stop. They also make ADR-0026's resolver see two owners for one label and
correctly refuse to anchor, so plates lose their character reference.

## Decision

Three further rules in `_filter_published_aliases`, all deterministic and all conservative
(they forgo uncertain links; they never fabricate one):

1. **Shared → drop from everyone.** An alias claimed by more than one group identifies nobody and
   guarantees a cross-link. Do not pick a winner.
2. **Same name modulo title.** Compare on `names.core_key` (articles + honorifics stripped) as well
   as verbatim, so `elder`'s `"Zossima"` collides with the group named `"Father Zossima"`.
3. **Not a name.** An alias with no capitalised token is a role or relational epithet, never a name
   in the prose these books are drawn from.

Label folding moves to a new `scriptorium.names` module shared with `p7_render`, so cast reduction
and render-time matching cannot disagree about whether `"Father Zossima"` and `"Zossima"` are the
same person — disagreeing is precisely how a plate gets anchored on the wrong face.

## Consequences

- On the sample book: **731 → 199 aliases (73% dropped)**, with real name variants (`"Kalganov"`,
  `"Fyodor Pavlovitch Karamazov"`, `"Ilyitch"`, `"Mr. Kalganov"`) surviving.
- **Rule 3 assumes a capitalising script.** A book typeset entirely in lower case would lose its
  aliases. Canonical `name` values are never touched, so such a book still has a working cast — it
  just gets no alias matching. Accepted deliberately (Kris's call) as the cheapest big win; revisit
  with a per-bake flag if a real book regresses.
- **Rule 1 has a known cost when a character is split in two.** `pyotr-ilyitch` and
  `pyotr-ilyitch-perhotin` are one man, and both claim `"Perhotin"`, so it is now dropped from both.
  That is the safe outcome for a genuine defect elsewhere: the *split* is the bug, and merging it
  needs world knowledge, which stays the external service's job (ADR-0019).
- Filtering cannot repair what never arrives clean — `fyodor-pavlovitch` still carries `"Kalganov"`
  and `"Smurov"`, other characters entirely, because nothing downstream can know they are wrong.
  That is fixed at source in `text-transform-service` T20.
- **Existing published books are unaffected.** `cast.json` is written at bake time; these rules
  apply to the next bake. A published book only benefits from a re-bake.

## Not decided here

- **Merging split characters** (`elder` / `elder-zossima` / `father-zossima` are one man, three
  portraits). Needs world knowledge; deferred to the text service per ADR-0019.
- Repairing an already-published `cast.json` in place. Not attempted — re-bake instead.
