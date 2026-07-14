"""Bake phase protocol + control-flow exceptions (DESIGN §7.3).

A *phase* advances a job from one state to the next by processing a set of *units*
(pages, characters, …). The runner drives phases uniformly; each phase only needs to
say what its units are, whether a unit is already done (by checking its checkpoint
artifact), and how to run one. Because ``unit_done`` reads a persisted artifact, a
phase re-entered after a crash skips finished units — the resumability invariant.

Exceptions model the three §7.3 failure classes:

- :class:`GpuUnavailable` — 503-class from a GPU service. The runner parks the job in
  ``waiting_gpu`` and retries each tick (with Wake-on-LAN, §7.4).
- :class:`UnitFailed` — 422-class, retriable. The runner runs the 3× backoff ladder;
  on exhaustion it records the unit in ``failed_units`` and continues the phase.
- :class:`PipelineBug` — 400/404/413/401/500-class from a GPU service (malformed request,
  unknown transform, over-budget input, auth, internal): a bug the pipeline can't retry
  around. It is deliberately a plain ``Exception`` so the runner's bug-class handler fails
  the whole job loudly (TTS DESIGN §8: "halt the phase loudly").
- Anything else = bug-class → the runner fails the whole job (human attention).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..job import Job


@dataclass(frozen=True)
class Unit:
    """One unit of work within a phase. ``payload`` is opaque to the runner."""

    id: str
    payload: Any = None


class GpuUnavailable(Exception):
    """A GPU service is unreachable (503-class) → ``waiting_gpu`` (§7.4)."""


class UnitFailed(Exception):
    """A unit failed retriably (422-class) → 3× ladder then ``failed_units`` (§7.3)."""


class PipelineBug(Exception):
    """A non-retriable GPU-service error (400/404/413/401/500) → job ``failed`` (§8).

    Not caught specially by the runner: it falls through to the bug-class handler and
    fails the whole job, which is exactly the "halt loudly" contract for these codes.
    """


@runtime_checkable
class Phase(Protocol):
    """The contract every bake phase implements."""

    name: str
    from_state: str
    to_state: str
    is_gpu: bool

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        """The units this phase must process for ``job`` (deterministic order)."""
        ...

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:
        """True iff ``unit``'s checkpoint artifact already exists and parses."""
        ...

    def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:
        """Process one unit, writing its checkpoint artifact.

        May raise :class:`GpuUnavailable` or :class:`UnitFailed`; any other exception
        is treated as bug-class and fails the job.
        """
        ...
