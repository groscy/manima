"""The MANIMA MCP tool surface, as this harness understands it.

The harness is a *client* of the contract in ``openspec/specs`` — render, generate,
jobs, sandbox. It drives only the documented tools and never reaches into server
internals (proposal.md, "Out"). Everything here is derived from the specs, not from
a running server; where a spec leaves a wire detail open, the choice is marked
ASSUMPTION so a mismatch against the real server is easy to find and fix.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class JobState(str, Enum):
    """Job state machine from ``specs/jobs`` — "Job state SHALL follow a defined machine".

    The only backward edge is ``RENDERING``/``VALIDATING`` -> ``GENERATING`` (repair).
    """

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


# Tool names — the public surface. render/generate enqueue; the job tools observe.
TOOL_RENDER = "render_animation"
TOOL_GENERATE = "generate_animation"
TOOL_JOB_STATUS = "job_status"
TOOL_JOB_RESULT = "job_result"
TOOL_CANCEL = "cancel_job"


@dataclass
class TimedCall:
    """One tool call and how long the *call* took (not the render it enqueued).

    Lives here, in the mcp-free contract module, so the instrumentation layer can
    consume it without importing the MCP client (keeping the offline analysis path
    dependency-light).
    """

    tool: str
    latency_s: float
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JobHandle:
    """What ``render_animation`` / ``generate_animation`` return, "immediately"."""

    job_id: str


@dataclass(frozen=True)
class JobStatus:
    """``job_status`` — cheap, never blocks. Returns ``state``, ``attempt``, ``phase``."""

    state: JobState
    attempt: int
    phase: str | None = None


@dataclass(frozen=True)
class Attempt:
    """One entry in a job ``trace``.

    ``specs/jobs`` pins the *content* of the trace ("generator identity per attempt,
    each traceback, the attempt count, and the escalation flag") but not its wire
    shape. The field names below are an ASSUMPTION; ``from_raw`` accepts a few common
    spellings so a shape mismatch degrades to ``None`` fields rather than a crash.
    """

    index: int
    generator: str | None
    source: str | None
    traceback: str | None
    escalated: bool = False

    @classmethod
    def from_raw(cls, index: int, raw: dict[str, Any]) -> "Attempt":
        return cls(
            index=index,
            generator=_first(raw, "generator", "generator_identity", "model"),
            source=_first(raw, "source", "code", "candidate"),
            traceback=_first(raw, "traceback", "error", "trace"),
            escalated=bool(_first(raw, "escalated", "escalation", default=False)),
        )


@dataclass(frozen=True)
class JobResult:
    """``job_result`` — valid only in terminal states.

    Returns ``artifact_uri``, ``source``, and ``trace``. For a generate job the trace
    carries the full attempt history; for a render job it is typically a single entry.
    """

    state: JobState
    artifact_uri: str | None
    source: str | None
    attempts: list[Attempt] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.state is JobState.SUCCEEDED

    @property
    def final_traceback(self) -> str | None:
        for attempt in reversed(self.attempts):
            if attempt.traceback:
                return attempt.traceback
        return None


# --- parse helpers -------------------------------------------------------------
# MCP tool results carry content blocks and, on newer servers, a structuredContent
# dict. The specs don't pin which MANIMA uses, so we accept both: prefer structured
# content, fall back to JSON parsed out of the first text block.


def payload_from_tool_result(structured: Any, text: str | None) -> dict[str, Any]:
    """Normalise an MCP CallToolResult into a plain dict.

    ``structured`` is ``CallToolResult.structuredContent`` (or ``None``); ``text`` is
    the concatenated text content. ASSUMPTION: whichever is present decodes to a JSON
    object. Raises ``ContractError`` if neither yields one — a real, reportable
    finding about the surface rather than a silent empty result.
    """

    if isinstance(structured, dict) and structured:
        return structured
    if text:
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ContractError(f"tool result text was not JSON: {text!r}") from exc
        if isinstance(decoded, dict):
            return decoded
    raise ContractError("tool result carried no structured or JSON object payload")


def parse_job_handle(payload: dict[str, Any]) -> JobHandle:
    job_id = _first(payload, "job_id", "jobId", "id")
    if not job_id:
        raise ContractError(f"no job_id in enqueue result: {payload!r}")
    return JobHandle(job_id=str(job_id))


def parse_job_status(payload: dict[str, Any]) -> JobStatus:
    raw_state = _first(payload, "state", "status")
    return JobStatus(
        state=_coerce_state(raw_state),
        attempt=int(_first(payload, "attempt", "attempts", default=0) or 0),
        phase=_first(payload, "phase"),
    )


def parse_job_result(payload: dict[str, Any]) -> JobResult:
    raw_trace = _first(payload, "trace", "attempts", default=[]) or []
    attempts = [
        Attempt.from_raw(i, a)
        for i, a in enumerate(raw_trace)
        if isinstance(a, dict)
    ]
    return JobResult(
        state=_coerce_state(_first(payload, "state", "status")),
        artifact_uri=_first(payload, "artifact_uri", "artifactUri", "path"),
        source=_first(payload, "source", "final_source"),
        attempts=attempts,
        raw=payload,
    )


def _coerce_state(value: Any) -> JobState:
    if isinstance(value, JobState):
        return value
    try:
        return JobState(str(value).upper())
    except ValueError as exc:
        raise ContractError(f"unknown job state {value!r}") from exc


def _first(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


class ContractError(RuntimeError):
    """The server returned something the documented surface doesn't describe.

    Per proposal.md ("Out"), this is itself a finding: record it rather than
    reaching around the surface to paper over it.
    """
