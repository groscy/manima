"""Ports — the boundaries the core depends on (design D1, task 1.3).

Each is a Protocol the core programs against; adapters in ``manima_server.adapters``
implement them. The core imports this module, never an adapter, so the generator, the
sandbox, the store, the grounding, and the job persistence are all swappable and the
core is testable with fakes (specs/generate: "generator is swapped" → no core change).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain import Job, RenderMode, RenderOutcome


@runtime_checkable
class SandboxExecutor(Protocol):
    """Run untrusted Manim CE source inside a contained sandbox (specs/sandbox).

    There is no non-sandboxed variant of this port — every execution path in the server
    goes through an implementation of it (invariant 1).
    """

    async def run(
        self,
        source: str,
        *,
        mode: RenderMode,
        scene_name: str | None = None,
        quality: str = "low",
        name: str | None = None,
    ) -> RenderOutcome:
        """Execute ``source`` in a contained sandbox and return the mechanical verdict.

        ``name`` labels the underlying container so ``cancel_job`` can ``kill`` it
        mid-render (task 4.5)."""
        ...

    async def kill(self, name: str) -> None:
        """Kill a running sandbox by name. No-op if it is already gone."""
        ...

    def preflight(self) -> None:
        """Raise if the sandbox cannot operate (e.g. Docker daemon unreachable).

        Called at server startup; a failure here MUST stop the server, loudly, with no
        host-execution fallback (specs/sandbox)."""
        ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Content-addressed artifact storage keyed by (source, quality, manim_version)."""

    def key_for(self, source: str, quality: str) -> str: ...

    def get(self, key: str) -> str | None:
        """Return the artifact path if present (a cache hit), else None."""
        ...

    def put(self, key: str, artifact_path: str) -> str:
        """Store the artifact and return its stable URI/path. Never inlines bytes."""
        ...

    def reap(self) -> list[str]:
        """Remove artifacts past their retention window; return the keys reaped."""
        ...


@runtime_checkable
class GroundingRetriever(Protocol):
    """Retrieve top-k pinned-version Manim CE API snippets for a prompt (specs/generate)."""

    async def retrieve(self, prompt: str, k: int = 8) -> list[str]: ...


@runtime_checkable
class AnimationGenerator(Protocol):
    """Turn a prompt (plus grounding and optional repair context) into Manim CE source.

    Apertus 8B via vLLM is one adapter; the escalation model is another (specs/generate).
    """

    @property
    def identity(self) -> str:
        """Stable label recorded per attempt in the job trace (e.g. the model id)."""
        ...

    async def generate(
        self,
        prompt: str,
        *,
        grounding: list[str],
        repair_source: str | None = None,
        repair_traceback: str | None = None,
    ) -> str: ...


@runtime_checkable
class JobStore(Protocol):
    """Durable persistence for jobs, their state, and their trace (design D7)."""

    def create(self, job: Job) -> None: ...

    def save(self, job: Job) -> None: ...

    def load(self, job_id: str) -> Job | None: ...

    def expired(self, now: float) -> list[Job]:
        """Jobs whose retention window has elapsed, for the TTL reaper."""
        ...


__all__ = [
    "SandboxExecutor",
    "ArtifactStore",
    "GroundingRetriever",
    "AnimationGenerator",
    "JobStore",
]
