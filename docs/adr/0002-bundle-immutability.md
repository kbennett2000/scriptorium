# ADR 0002: Bundle immutability, additive revisions, and the publish integrity guard

- **Status:** Accepted
- **Date:** 2026-07-13

## Context

Annotations are character offsets into a page's text. If published text could
change, every anchor into it could silently break. Readers also sync bundles by
delta, so the format must make "what changed" unambiguous and safe. See DESIGN
§4.4 (and §1 principle 2).

## Decision

After first publish, a bundle's core identity fields in `meta`, all of
`structure.json`, and every `pages/*.json` **text** (and its `ledger`, which is
provenance) are frozen. Revisions are **additive**: a re-selection or a plate
re-render may add files and update `selection.json`, `prompts/*`, `meta.stats`,
and `manifest.json`, bumping `revision`. Plates are never deleted; a deselected
plate becomes `status: "retired"` and its files remain. Client delta sync is a
manifest diff by path + sha256: download new/changed, never delete text, may
prune `retired` plate images locally.

A **publish-time integrity guard** enforces this: if `library/{id}` already
exists, every existing `pages/*.json` must be byte-identical to the new bake's,
or publish refuses.

## Consequences

- Annotation anchors are permanently safe against re-bakes.
- Storage grows monotonically with revisions (retired plates retained); accepted.
- The integrity guard is a hard check in the publish phase (cycle S10), tested by
  attempting to republish a bundle with a mutated page byte.
