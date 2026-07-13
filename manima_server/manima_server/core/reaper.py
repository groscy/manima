"""TTL reaping (tasks 11.1-11.2, specs/jobs).

Two coupled effects when an artifact's retention window elapses: the bytes are removed
from the store, and the owning job transitions to ``EXPIRED`` so ``job_result`` reports
expiry rather than handing back a dangling path.

Pure orchestration over the ``ArtifactStore`` and ``JobStore`` ports — testable without a
real filesystem or a running server.
"""

from __future__ import annotations

from .domain import JobState
from .ports import ArtifactStore, JobStore
from .state_machine import can_transition


class Reaper:
    def __init__(self, job_store: JobStore, artifact_store: ArtifactStore) -> None:
        self._jobs = job_store
        self._store = artifact_store

    def reap(self, now: float) -> int:
        """Remove expired artifacts and expire their jobs. Returns the job count expired."""

        # 1. Drop the bytes for anything past its TTL.
        self._store.reap()
        # 2. Expire the jobs whose window has elapsed.
        expired = 0
        for job in self._jobs.expired(now):
            if can_transition(job.state, JobState.EXPIRED):
                job.state = JobState.EXPIRED
                job.phase = "expired"
                # The path is gone; drop it so nothing hands back a dangling reference.
                job.artifact_uri = None
                job.touch()
                self._jobs.save(job)
                expired += 1
        return expired
