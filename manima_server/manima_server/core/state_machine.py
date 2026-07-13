"""The job state machine (task 4.3, specs/jobs).

One transition table, enforced in one place. The only backward edge is
``RENDERING``/``VALIDATING`` -> ``GENERATING`` — the repair edge — and it is the only way
the attempt counter advances. Every other move is forward or into a terminal state.
Illegal transitions raise, so a bug that tries to skip validation or resurrect a
terminal job fails loudly instead of corrupting the trace.
"""

from __future__ import annotations

from .domain import JobState

# from_state -> allowed next states.
_ALLOWED: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset(
        {JobState.GENERATING, JobState.VALIDATING, JobState.CANCELLED, JobState.FAILED}
    ),
    JobState.GENERATING: frozenset(
        {JobState.VALIDATING, JobState.CANCELLED, JobState.FAILED}
    ),
    JobState.VALIDATING: frozenset(
        # -> GENERATING is the repair edge (backward).
        {JobState.RENDERING, JobState.GENERATING, JobState.CANCELLED, JobState.FAILED}
    ),
    JobState.RENDERING: frozenset(
        # -> GENERATING is the repair edge (backward).
        {JobState.SUCCEEDED, JobState.FAILED, JobState.GENERATING, JobState.CANCELLED}
    ),
    # Terminal-but-reapable: TTL can expire a finished job (specs/jobs).
    JobState.SUCCEEDED: frozenset({JobState.EXPIRED}),
    JobState.FAILED: frozenset({JobState.EXPIRED}),
    JobState.CANCELLED: frozenset({JobState.EXPIRED}),
    JobState.EXPIRED: frozenset(),
}

# The repair edges — the only backward transitions the machine permits.
REPAIR_EDGES: frozenset[tuple[JobState, JobState]] = frozenset(
    {
        (JobState.VALIDATING, JobState.GENERATING),
        (JobState.RENDERING, JobState.GENERATING),
    }
)


def can_transition(src: JobState, dst: JobState) -> bool:
    return dst in _ALLOWED.get(src, frozenset())


def is_repair_edge(src: JobState, dst: JobState) -> bool:
    return (src, dst) in REPAIR_EDGES


def assert_transition(src: JobState, dst: JobState) -> None:
    if not can_transition(src, dst):
        raise InvalidTransition(f"illegal job transition {src.value} -> {dst.value}")


class InvalidTransition(RuntimeError):
    """An attempt to move a job along an edge the state machine does not permit."""
