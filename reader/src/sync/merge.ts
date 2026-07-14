import type { Annotations, Positions } from "@scriptorium/shared";

// A bit-for-bit TypeScript port of `server/src/scriptorium/sync/merge.py` (DESIGN §12). The server is
// authoritative — R3's engine adopts the server's merged doc wholesale — but the sync engine also
// canonicalizes the LOCAL doc before PUT (dedup / tombstone hygiene while offline), so this port must
// converge to exactly the same result the server would. The two impls are pinned against ONE vector
// file (`shared/test-vectors/sync-merge.json`), consumed by `merge.test.ts` here and
// `server/tests/test_sync_vectors.py`; a drift reddens one of the two suites.
//
// Timestamps are compared as ISO-8601 STRINGS, never parsed to Date: they are always UTC and
// second-or-finer precision (JS `Date.toISOString()`), so lexicographic order equals chronological
// order. Do not "improve" this to Date parsing — string compare is the contract.

type Annotation = Annotations["annotations"][number];
type Position = Positions["current"];

/**
 * Reproduce Python's `json.dumps(value, sort_keys=True, ensure_ascii=False)` for the annotation value
 * domain (objects, strings, integers, booleans). This is the deterministic tiebreak used when two
 * copies of an annotation share an `id` AND a `modified` timestamp, so it must match the server byte
 * for byte: object keys sorted, `", "` / `": "` separators, non-ASCII left raw. A naive
 * `JSON.stringify` (no spaces, escapes non-ASCII) would diverge on that degenerate case.
 */
export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") {
    // Scalars: JSON.stringify already matches Python for strings (raw non-ASCII), ints, and booleans.
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(", ")}]`;
  }
  const keys = Object.keys(value as Record<string, unknown>).sort();
  const body = keys
    .map((k) => `${JSON.stringify(k)}: ${canonicalJson((value as Record<string, unknown>)[k])}`)
    .join(", ");
  return `{${body}}`;
}

/** Which of two same-`id` annotations wins: greater `modified`, then full-doc canonical-JSON tiebreak. */
function annotationPickKey(ann: Annotation): [string, string] {
  return [ann.modified, canonicalJson(ann)];
}

/** Total order on the pick key: greater `modified`, then greater canonical JSON (both string compares). */
function pickKeyGreater(a: [string, string], b: [string, string]): boolean {
  if (a[0] !== b[0]) return a[0] > b[0];
  return a[1] > b[1];
}

/** Dedup a doc's annotations by `id` (winner kept) and sort ascending by `id` — the canonical form. */
function canonicalAnnotations(doc: Annotations): Annotations {
  const best = new Map<string, Annotation>();
  for (const ann of doc.annotations) {
    const cur = best.get(ann.id);
    if (cur === undefined || pickKeyGreater(annotationPickKey(ann), annotationPickKey(cur))) {
      best.set(ann.id, ann);
    }
  }
  const ordered = [...best.values()].sort((x, y) => (x.id < y.id ? -1 : x.id > y.id ? 1 : 0));
  return { book_id: doc.book_id, user_id: doc.user_id, annotations: ordered };
}

/**
 * Merge two annotation docs (DESIGN §12): union by `id`, last-writer-wins by `modified`. Tombstones
 * (`deleted: true`) are ordinary entries — a later delete beats an earlier edit and vice versa
 * (deletion can lose; documented). Output is canonical (deduped, sorted by `id`). Identity comes from
 * `a` (falling back to `b`). Commutative, associative, idempotent (`merge(x, x) == canonical(x)`).
 */
export function mergeAnnotations(a: Annotations, b: Annotations): Annotations {
  const identity = a.book_id ? a : b;
  const combined: Annotations = {
    book_id: identity.book_id,
    user_id: identity.user_id,
    annotations: [...a.annotations, ...b.annotations],
  };
  return canonicalAnnotations(combined);
}

/** `furthest` order: by `(page_seq, char)` — furthest-read-wins; `modified` only tiebreaks a tie. */
function furthestGreater(a: Positions["furthest"], b: Positions["furthest"]): boolean {
  if (a.page_seq !== b.page_seq) return a.page_seq > b.page_seq;
  if (a.char !== b.char) return a.char > b.char;
  return a.modified > b.modified;
}

/** `current` order: LWW by `modified`, then `(page_seq, char, device)` as a deterministic tiebreak. */
function currentGreater(a: Position, b: Position): boolean {
  if (a.modified !== b.modified) return a.modified > b.modified;
  if (a.page_seq !== b.page_seq) return a.page_seq > b.page_seq;
  if (a.char !== b.char) return a.char > b.char;
  return (a.device ?? "") > (b.device ?? "");
}

/**
 * Merge two position docs (DESIGN §12): `furthest` = max by `(page_seq, char)` regardless of
 * timestamp (never regresses); `current` = last-writer-wins by `modified`. Commutative, associative,
 * idempotent.
 */
export function mergePositions(a: Positions, b: Positions): Positions {
  return {
    furthest: furthestGreater(b.furthest, a.furthest) ? b.furthest : a.furthest,
    current: currentGreater(b.current, a.current) ? b.current : a.current,
  };
}
