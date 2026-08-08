"""P2 cast reducer (DESIGN §7.2) — deterministic, pure, CPU-only.

Takes the per-page ``cast-mentions`` outputs (P1) and folds them into one grouped,
canonical-name-per-character list. This is the fiddly half of P2; it is a **pure function**
(no I/O, no clock, no randomness) so it can be unit-tested exhaustively against hand-built
mention fixtures — including the Weena/Eloi co-occurrence guard.

The function returns *groups*, which include the reducer intermediates ``is_person`` and
``descriptors``. Those are **not** part of the published ``cast.json`` contract (see that
schema's top-level note); the P2 phase strips them and calls ``cast-canonicalize`` for the
majors. Here we only compute the grouping, the ``major`` flag, and the slug.

Steps implemented verbatim from §7.2:

1. Normalize labels (trim, collapse whitespace, strip possessive ``'s``, casefold — for
   matching only; display keeps the most-frequent original casing).
2. Union-find grouping on (a) exact normalized match, (b) label appears in another mention's
   ``aliases``, (c) single-token subset of the other's content tokens (tokens minus
   articles/honorifics). **Never** merge two labels that co-occur as distinct entries on the
   same page (the guard).
3. Per group: ``name`` = most-frequent full label; ``aliases`` = the rest; ``mention_pages``
   = union; ``descriptors`` = concatenated, order-preserving, dup-deduped, capped at 40.
4. ``is_person`` = majority vote.
5. ``major`` = person groups on ≥3 pages, or the top-6 persons by page count — whichever set
   is larger.
7. ``slug`` = kebab-case of the de-articled name, uniquified with ``-2`` suffixes.

**Deviation (approved, logged in CYCLE-LOG as a §7.2 amendment):** mentions whose normalized name
is a bare pronoun are dropped *before* grouping — T5's live first-person narration surfaces
unattributable ``"I"`` mentions whose descriptors can't be assigned.

**ADR-0019 (character alias/junk):** the pre-grouping drop is extended from subject pronouns to all
pronoun/indefinite whole-name stop-words (``_STOP_NAMES``, catches "me"); single-page all-lowercase
generic-noun groups are dropped after grouping (``_drop_junk_groups``, before the major flag); rule
2c never merges on a token shared by ≥2 full names (ambiguous patronymic/surname), and merges an
unambiguous single-superset containment even across the same-page guard. Nickname/diminutive linking
(e.g. "Mitya"↔"Dmitri") is out of scope here — it needs the external ``cast-mentions`` transform to
emit the alias, since no in-repo string rule can link substring-disjoint names.
"""

from __future__ import annotations

import re
from typing import Any

# Rule (c): tokens stripped before the single-token-subset test (DESIGN §7.2 step 2c).
_ARTICLES_HONORIFICS: frozenset[str] = frozenset(
    {"the", "a", "mr", "mrs", "miss", "dr", "sir", "lady", "lord"}
)
# Slug de-articling (step 7) removes only leading articles, not honorifics.
_SLUG_ARTICLES: frozenset[str] = frozenset({"the", "a", "an"})
# Whole-name mentions dropped before grouping (approved §7.2 deviation, extended ADR-0019). A
# real named character is never one of these; dropping catches a stray "me"/"someone"/"this"
# that the LLM surfaced as a mention name. Only an EXACT whole-name match is dropped.
_STOP_NAMES: frozenset[str] = frozenset({
    # subject / object / possessive / reflexive pronouns
    "i", "he", "she", "they", "we", "you", "it",
    "me", "him", "her", "us", "them",
    "mine", "hers", "ours", "yours", "theirs",
    "myself", "yourself", "himself", "herself", "itself",
    "ourselves", "yourselves", "themselves",
    # indefinite / demonstrative pronouns
    "one", "someone", "somebody", "anyone", "anybody",
    "everyone", "everybody", "no one", "nobody",
    "something", "anything", "everything", "nothing",
    "this", "that", "these", "those", "who", "whom",
})

_DESCRIPTOR_CAP = 40
_MAJOR_PAGE_FLOOR = 3
_MAJOR_TOP_N = 6
# A group on fewer than this many pages whose display name is an all-lowercase generic noun
# ("peasant", "old woman", "another female figure") is dropped as junk (ADR-0019 A1). Kept
# deliberately tight — a capitalized name or a recurring role is never touched.
_JUNK_MAX_PAGES = 2
# When a single-token name is contained in EXACTLY ONE full name (unambiguous, e.g.
# "Dmitri" ⊆ "Dmitri Fyodorovitch"), merge it even across the same-page guard (ADR-0019 A3).
# Flip off if a specific book merges two co-occurring different people who share a given name.
_CONTAINMENT_OVERRIDES_GUARD = True

_WS = re.compile(r"\s+")
_POSSESSIVE = re.compile(r"['’]s$", re.IGNORECASE)


def _collapse_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _norm(label: str) -> str:
    """Normalized *matching* key: trim → collapse ws → strip possessive → casefold."""
    stripped = _POSSESSIVE.sub("", _collapse_ws(label))
    return _collapse_ws(stripped).casefold()


def _content_tokens(norm: str) -> list[str]:
    """Tokens of a normalized label minus articles/honorifics (for rule 2c)."""
    return [t for t in norm.split(" ") if t and t not in _ARTICLES_HONORIFICS]


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self._parent = {x: x for x in items}

    def find(self, x: str) -> str:
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:  # path compression
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


class _Record:
    """One normalized mention occurrence (post pronoun-drop)."""

    __slots__ = ("order", "page_id", "name_display", "name_norm",
                 "alias_norms", "alias_displays", "descriptors", "is_person")

    def __init__(self, order: int, page_id: str, mention: dict[str, Any]) -> None:
        self.order = order
        self.page_id = page_id
        self.name_display = _collapse_ws(str(mention.get("name", "")))
        self.name_norm = _norm(self.name_display)
        raw_aliases = [_collapse_ws(str(a)) for a in mention.get("aliases", [])]
        self.alias_displays = [a for a in raw_aliases if _norm(a)]
        self.alias_norms = [_norm(a) for a in self.alias_displays]
        self.descriptors = [
            _collapse_ws(str(d)) for d in mention.get("descriptors", []) if str(d).strip()
        ]
        self.is_person = bool(mention.get("is_person", True))


def reduce_cast(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce per-page mentions into grouped cast entries (DESIGN §7.2).

    ``pages`` is a list of ``{"page_id": "0001", "mentions": [<cast-mentions objects>]}``
    in page order. Returns a list of group dicts with keys ``slug, name, aliases,
    mention_pages, descriptors, is_person, major`` in first-seen order.
    """
    records = _collect_records(pages)
    if not records:
        return []

    nodes = _distinct_norms(records)
    uf = _group(records, nodes)

    groups = _build_groups(records, nodes, uf)
    groups = _drop_junk_groups(groups)  # before _mark_majors: junk can't take a major/portrait slot
    _mark_majors(groups)
    _assign_slugs(groups)
    return [_public_group(g) for g in groups]


# --- step 1: collect + pronoun-drop ----------------------------------------


def _collect_records(pages: list[dict[str, Any]]) -> list[_Record]:
    records: list[_Record] = []
    order = 0
    for page in pages:
        page_id = str(page.get("page_id", ""))
        for mention in page.get("mentions", []):
            name_norm = _norm(str(mention.get("name", "")))
            if not name_norm or name_norm in _STOP_NAMES:
                continue  # drop empty + stop-word (pronoun/indefinite) mentions before grouping
            records.append(_Record(order, page_id, mention))
            order += 1
    return records


def _distinct_norms(records: list[_Record]) -> list[str]:
    seen: dict[str, None] = {}  # dict preserves first-seen order
    for r in records:
        seen.setdefault(r.name_norm, None)
    return list(seen)


# --- step 2: union-find grouping with the co-occurrence guard ---------------


def _group(records: list[_Record], nodes: list[str]) -> _UnionFind:
    node_set = set(nodes)
    first_seen = {n: i for i, n in enumerate(nodes)}
    forbidden = _forbidden_pairs(records)
    uf = _UnionFind(nodes)

    def would_violate(x: str, y: str) -> bool:
        rx, ry = uf.find(x), uf.find(y)
        if rx == ry:
            return False
        roots = {rx, ry}
        for p, q in forbidden:
            rp, rq = uf.find(p), uf.find(q)
            if rp != rq and {rp, rq} == roots:
                return True  # this merge would co-locate a distinct-on-a-page pair
        return False

    # Collect candidate merges (rules b, c), then apply deterministically.
    candidates: set[tuple[str, str]] = set()

    # (b) a mention's declared alias names another known mention.
    for r in records:
        for a in r.alias_norms:
            if a in node_set and a != r.name_norm:
                candidates.add(_pair(r.name_norm, a))

    # (c) single-token subset of the other's content tokens — patronymic-safe.
    # A lone token contained in >= 2 distinct full names is an ambiguous shared patronymic/surname
    # ("Fyodorovitch" in both "Dmitri Fyodorovitch" and "Alexey Fyodorovitch") and must never drive
    # a merge (A2). A lone token contained in EXACTLY ONE full name is a candidate as before; it is
    # additionally marked *strong* — allowed to bypass the co-occurrence guard (A3) — only for a
    # PROPER containment, where the superset carries extra content tokens ("Dmitri" in "Dmitri
    # Fyodorovitch"). A mere article variant ("guard" vs "the guard", same single content token) is
    # NOT strong, so two co-occurring "Guards" still stay apart.
    content = {n: _content_tokens(n) for n in nodes}
    strong: set[tuple[str, str]] = set()
    for x in nodes:
        xt = content[x]
        if len(xt) != 1:
            continue
        token = xt[0]
        supersets = [y for y in nodes if y != x and token in content[y]]
        if len(supersets) != 1:
            continue  # 0 -> nothing to merge; >=2 -> ambiguous shared token -> never merge
        y = supersets[0]
        pair = _pair(x, y)
        candidates.add(pair)
        if len(content[y]) > 1:
            strong.add(pair)  # proper multi-token containment -> may bypass the guard (A3)

    for x, y in sorted(candidates, key=lambda p: (first_seen[p[0]], first_seen[p[1]])):
        strong_bypass = _CONTAINMENT_OVERRIDES_GUARD and _pair(x, y) in strong
        if strong_bypass or not would_violate(x, y):
            uf.union(x, y)
    return uf


def _forbidden_pairs(records: list[_Record]) -> list[tuple[str, str]]:
    """Distinct mention-name pairs that co-occur on the same page (never merge these)."""
    by_page: dict[str, list[str]] = {}
    for r in records:
        names = by_page.setdefault(r.page_id, [])
        if r.name_norm not in names:
            names.append(r.name_norm)
    pairs: set[tuple[str, str]] = set()
    for names in by_page.values():
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                pairs.add(_pair(names[i], names[j]))
    return sorted(pairs)


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


# --- steps 3-4: build one group per component -------------------------------


def _build_groups(
    records: list[_Record], nodes: list[str], uf: _UnionFind
) -> list[dict[str, Any]]:
    members: dict[str, list[_Record]] = {}
    for r in records:
        members.setdefault(uf.find(r.name_norm), []).append(r)

    # Emit groups in first-seen order of their root's earliest record.
    roots_in_order: list[str] = []
    seen_roots: set[str] = set()
    for r in records:
        root = uf.find(r.name_norm)
        if root not in seen_roots:
            seen_roots.add(root)
            roots_in_order.append(root)

    groups: list[dict[str, Any]] = []
    for root in roots_in_order:
        recs = sorted(members[root], key=lambda r: r.order)
        groups.append(_build_one_group(recs))
    return groups


def _build_one_group(recs: list[_Record]) -> dict[str, Any]:
    # Per-norm stats: frequency, most-frequent display casing, first-seen order.
    freq: dict[str, int] = {}
    first_order: dict[str, int] = {}
    display_votes: dict[str, dict[str, int]] = {}
    for r in recs:
        freq[r.name_norm] = freq.get(r.name_norm, 0) + 1
        first_order.setdefault(r.name_norm, r.order)
        votes = display_votes.setdefault(r.name_norm, {})
        votes[r.name_display] = votes.get(r.name_display, 0) + 1

    def display_of(norm: str) -> str:
        votes = display_votes[norm]
        return max(votes, key=lambda d: (votes[d], -_first_display_order(recs, d)))

    # name = most-frequent full label (tie → earliest, then lexicographic display).
    ordered_norms = sorted(
        freq, key=lambda n: (-freq[n], first_order[n], display_of(n))
    )
    name_norm = ordered_norms[0]
    name = display_of(name_norm)

    # aliases: other label variants (freq desc, first-seen), then declared aliases.
    aliases: list[str] = []
    alias_norm_seen = {name_norm}
    for n in ordered_norms[1:]:
        aliases.append(display_of(n))
        alias_norm_seen.add(n)
    for r in recs:  # declared per-mention aliases not already surfaced
        for a_norm, a_disp in _declared_alias_pairs(r):
            if a_norm and a_norm not in alias_norm_seen:
                aliases.append(a_disp)
                alias_norm_seen.add(a_norm)

    mention_pages = sorted({r.page_id for r in recs})

    descriptors: list[str] = []
    desc_seen: set[str] = set()
    for r in recs:
        for d in r.descriptors:
            if d not in desc_seen:
                desc_seen.add(d)
                descriptors.append(d)
    descriptors = descriptors[:_DESCRIPTOR_CAP]

    persons = sum(1 for r in recs if r.is_person)
    is_person = persons >= (len(recs) - persons)  # majority; tie → person

    return {
        "name": name,
        "aliases": aliases,
        "mention_pages": mention_pages,
        "descriptors": descriptors,
        "is_person": is_person,
        "_order": min(r.order for r in recs),
    }


def _declared_alias_pairs(rec: _Record) -> list[tuple[str, str]]:
    return list(zip(rec.alias_norms, rec.alias_displays, strict=False))


def _first_display_order(recs: list[_Record], display: str) -> int:
    for r in recs:
        if r.name_display == display:
            return r.order
    return len(recs)


# --- junk drop (ADR-0019 A1): all-lowercase generic single-page groups --------


def _is_lowercase_generic(name: str) -> bool:
    """True if ``name`` (after a leading article) has no capital — a generic noun, not a name.

    Real named characters and the pipeline's role designations are title-cased ("the Time
    Traveller", "the Psychologist"); junk the LLM surfaces is lowercase ("peasant", "old woman",
    "another female figure"). Uses the *display* name so casing is meaningful.
    """
    tokens = name.split()
    while tokens and tokens[0].lower() in _SLUG_ARTICLES:
        tokens.pop(0)
    tail = " ".join(tokens)
    return bool(tail) and not any(ch.isupper() for ch in tail)


def _drop_junk_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop single-page, all-lowercase generic-noun groups (conservative).

    Both conditions must hold, so a capitalized name (any page count) and a recurring lowercase role
    (>= ``_JUNK_MAX_PAGES`` pages) are always kept. ``is_person`` is deliberately NOT used: a junk
    "peasant" is a person, and the non-person collective (e.g. "the Morlocks") must survive.
    """
    return [
        g
        for g in groups
        if not (len(g["mention_pages"]) < _JUNK_MAX_PAGES and _is_lowercase_generic(g["name"]))
    ]


# --- step 5: major flag -----------------------------------------------------


def _mark_majors(groups: list[dict[str, Any]]) -> None:
    persons = [g for g in groups if g["is_person"]]
    floor_set = {id(g) for g in persons if len(g["mention_pages"]) >= _MAJOR_PAGE_FLOOR}
    by_pages = sorted(
        persons, key=lambda g: (-len(g["mention_pages"]), g["_order"])
    )
    top_set = {id(g) for g in by_pages[:_MAJOR_TOP_N]}
    major_ids = floor_set if len(floor_set) >= len(top_set) else top_set
    for g in groups:
        g["major"] = id(g) in major_ids


# --- step 7: slugs ----------------------------------------------------------


def _assign_slugs(groups: list[dict[str, Any]]) -> None:
    used: dict[str, int] = {}
    for g in groups:
        base = _slug(g["name"])
        if base not in used:
            used[base] = 1
            g["slug"] = base
        else:
            used[base] += 1
            g["slug"] = f"{base}-{used[base]}"


def _slug(name: str) -> str:
    tokens = [t for t in _norm(name).split(" ") if t]
    while tokens and tokens[0] in _SLUG_ARTICLES:
        tokens.pop(0)
    kebab = re.sub(r"[^a-z0-9]+", "-", " ".join(tokens)).strip("-")
    return kebab or "character"


def _public_group(g: dict[str, Any]) -> dict[str, Any]:
    return {
        "slug": g["slug"],
        "name": g["name"],
        "aliases": g["aliases"],
        "mention_pages": g["mention_pages"],
        "descriptors": g["descriptors"],
        "is_person": g["is_person"],
        "major": g["major"],
    }
