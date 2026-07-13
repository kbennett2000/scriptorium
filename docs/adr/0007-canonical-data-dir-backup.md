# ADR 0007: The i5 data dir is canonical and must be backed up off-box

- **Status:** Accepted
- **Date:** 2026-07-13

## Context

`SCRIPTORIUM_DATA` on the i5 (default `/var/lib/scriptorium`) holds the published
library, bake workspaces, sync annotations/positions and their backups, users, and
jobs. It is the only irreplaceable data in the system — everything else can be
rebuilt from source and the pipeline. See DESIGN §3.

## Decision

The i5 data directory is canonical. An **off-box backup** (restic, or rsync to
another machine — the mechanism is the operator's choice) must exist and be
verified before milestone M1 is declared done. The requirement is not optional;
the mechanism is.

## Consequences

- M1's acceptance checklist includes "ADR-0007 backup exists" (DESIGN §16).
- Loss of the i5 disk without this backup loses every reader's annotations and the
  published library; with it, recovery is a restore.
- In-bundle content (text, images) is reproducible from `work/{id}/source/` and the
  pipeline; annotations and positions are not, so the backup's real payload is the
  `sync/` and `users.json` data.
