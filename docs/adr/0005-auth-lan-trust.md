# ADR 0005: Authentication — profile-picker LAN trust

- **Status:** Accepted
- **Date:** 2026-07-13

## Context

Scriptorium is a household system on a trusted LAN with multiple readers. Passwords
would add friction for no threat we are defending against at home. See DESIGN §11
(auth note) and §14.

## Decision

There is no authentication in v1. Household members are chosen from a passwordless
profile picker; per-user annotations and positions are namespaced by profile id.
The admin API group is additionally protected only by binding — the admin UI is
linked and reachable on the LAN. An optional TTS-style shared-secret for the admin
group is reserved in config but not built.

## Consequences

- No credential storage, reset flows, or session management to build or secure.
- If LAN trust ever feels too thin for the admin surface, the reserved shared
  secret can be turned on without a redesign.
- Per-user separation is a namespacing convenience, not a security boundary.
