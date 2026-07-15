"""Per-user picture "sets" for a book (DESIGN §8, ADR-0014).

A *set* changes only how a book's illustrations look, never which pages are illustrated
(that layout lives in the book's shared, immutable ``selection.json``). Sets are private
per household profile and additive — they never touch the published bundle. Every book has
a synthetic ``default`` set: its shipped bundle art, which every profile starts on.

Phase 1 exposes a read-only listing (default only); generation, offline delivery, and
deletion arrive in later cycles.
"""
