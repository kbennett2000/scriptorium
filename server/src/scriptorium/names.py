"""Person-label normalisation shared by cast reduction and render-time reference matching.

Two places need to decide whether two labels name the same person: :mod:`scriptorium.bake.
reduce_cast` (is this alias really another character's name?) and
:mod:`scriptorium.bake.phases.p7_render` (which cast entry does ``depicted[0]`` mean?). They must
agree — "Father Zossima" and "Zossima" being the same person in one place and different in the
other is how a plate ends up anchored on the wrong face — so the folding lives here once.

Deliberately dumb and deterministic: strip punctuation, casefold, drop leading articles and
honorifics. No diminutive/nickname linking ("Mitya" ↔ "Dmitri") — that needs world knowledge and
stays the external text service's job (ADR-0019).
"""

from __future__ import annotations

import re
from typing import Any

#: Leading words that are never part of a name.
ARTICLES: frozenset[str] = frozenset({"the", "a", "an"})

#: Titles that precede a name. Stripped so "Madame Hohlakov" ≡ "Hohlakov" and
#: "Father Zossima" ≡ "Zossima". ``elder`` is here because 19th-c. Russian translations use it as a
#: title ("Elder Zossima"), not as a given name.
HONORIFICS: frozenset[str] = frozenset({
    "mr", "mrs", "ms", "miss", "madame", "madam", "mme", "monsieur", "sir", "lady", "lord",
    "father", "fr", "elder", "brother", "sister", "saint", "st", "dr", "doctor",
    "captain", "colonel", "general", "lieutenant", "pan", "pani", "prince", "princess",
})

_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)


def tokens(label: Any) -> list[str]:
    """Case-folded word tokens of a label, punctuation stripped."""
    return _PUNCT.sub(" ", str(label)).casefold().split()


def core_tokens(label: Any) -> list[str]:
    """:func:`tokens` minus leading articles/honorifics — the identifying part of a label."""
    toks = tokens(label)
    i = 0
    while i < len(toks) and (toks[i] in ARTICLES or toks[i] in HONORIFICS):
        i += 1
    return toks[i:]


def core_key(label: Any) -> str:
    """A single comparable key for a label ("Father Zossima" and "Zossima" → ``"zossima"``)."""
    return " ".join(core_tokens(label))


def has_capitalised_token(label: Any) -> bool:
    """Whether any token starts with a capital — i.e. the label looks like a *name*.

    In the prose these books are drawn from, a character's name is capitalised and a role or
    relational epithet is not ("the old man", "the boy", "mamma", "his friend"). Used to keep such
    epithets out of published aliases, where they cross-link unrelated characters.
    """
    return any(t[:1].isupper() for t in str(label).split())
