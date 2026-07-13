"""Core domain types (task 1.4).

Pure data and enums — no I/O, no adapter imports — so the whole domain is unit-testable
without Docker or a GPU. The state machine's transition rules live in ``state_machine``;
this module defines the vocabulary those rules operate on.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class JobState(str, Enum):
    """The job lifecycle (specs/jobs)."""

    QUEUED = "QUEUED"
    GENERATING = "GENERATING"
    VALIDATING = "VALIDATING"
    RENDERING = "RENDERING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"

    @property
    def terminal(self) -> bool:
        return self in _TERMINAL_STATES


_TERMINAL_STATES = frozenset(
    {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED, JobState.EXPIRED}
)


class RenderMode(str, Enum):
    """A probe render is a 240p single-frame correctness oracle; a full render is the
    real artifact. They carry separate timeout budgets (specs/sandbox)."""

    PROBE = "probe"
    FULL = "full"


class Tool(str, Enum):
    RENDER = "render_animation"
    GENERATE = "generate_animation"


@dataclass
class RenderOutcome:
    """The result of executing source in the sandbox — the mechanical oracle's verdict.

    ``ok`` is ground truth: the scene rendered or it did not. On failure the traceback is
    captured verbatim as repair context; ``timed_out`` / ``oom`` distinguish the sandbox
    kill reasons so the job's error is honest about what happened.
    """

    ok: bool
    mode: RenderMode
    artifact_path: str | None = None
    traceback: str | None = None
    duration_s: float | None = None
    timed_out: bool = False
    oom: bool = False


@dataclass
class Attempt:
    """One generation/render attempt within a job's trace.

    Honest tracing (specs/jobs): generator identity, the source it produced, the
    traceback it hit, and whether escalation was involved — recorded per attempt so a
    successful result never conceals a difficult path to it.
    """

    index: int
    generator: str | None = None
    source: str | None = None
    traceback: str | None = None
    escalated: bool = False


@dataclass
class Job:
    """A unit of work. Tools enqueue one and return its id within 2 s (specs/jobs)."""

    job_id: str
    tool: Tool
    state: JobState = JobState.QUEUED
    attempt: int = 0
    phase: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    trace: list[Attempt] = field(default_factory=list)
    artifact_uri: str | None = None
    source: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # Retention: when set and elapsed, the TTL reaper expires the job (specs/jobs).
    expires_at: float | None = None
    escalated: bool = False

    def touch(self) -> None:
        self.updated_at = time.time()

    def add_attempt(self, attempt: Attempt) -> None:
        self.trace.append(attempt)
        self.attempt = attempt.index + 1
        self.touch()

    @property
    def last_traceback(self) -> str | None:
        for attempt in reversed(self.trace):
            if attempt.traceback:
                return attempt.traceback
        return None

    @property
    def best_effort_source(self) -> str | None:
        """The most recent source produced, for a FAILED job's caller to take over."""

        for attempt in reversed(self.trace):
            if attempt.source:
                return attempt.source
        return self.source
