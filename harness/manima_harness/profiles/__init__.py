"""Workload profiles (section 2) and the shared machinery they run on.

Each profile is a different *shape* of load on the same public surface:

    soak         one call at a time, sustained            memory / KV-cache / thermals
    burst        N concurrent generate calls              vLLM queueing, job manager
    repair-heavy prompts picked to fail first pass         the repair loop at worst case
    mixed        render and generate interleaved           contention between the paths

The base class owns everything common: enqueue a job, poll it to a terminal state while
recording state transitions, pull the result, and persist every attempt (task 2.6) —
plus a background sampler that ticks the Apertus side channel throughout the run.
Profiles only decide *what* to submit and *with how much concurrency*.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import AsyncIterator

import anyio

from ..client import ManimaClient
from ..config import HarnessConfig
from ..contract import JobStatus
from ..generators import SourceGenerator
from ..instrument import ApertusMetrics, ManimaMetrics
from ..prompts import Prompt, PromptSuite
from ..record import RecordStore, RunRecord

# Condition labels — recorded on every run so section-5 analysis can slice by it.
COND_APERTUS = "apertus"  # server-side generate_animation (the local model)


class Profile(ABC):
    name: str = "base"

    def __init__(
        self,
        config: HarnessConfig,
        suite: PromptSuite,
        store: RecordStore,
        manima_metrics: ManimaMetrics,
        apertus_metrics: ApertusMetrics,
    ) -> None:
        self.config = config
        self.suite = suite
        self.store = store
        self.manima = manima_metrics
        self.apertus = apertus_metrics

    @abstractmethod
    async def run(self, client: ManimaClient) -> list[RunRecord]:
        """Drive the workload. Return one RunRecord per job completed."""

    # -- shared job execution ---------------------------------------------------

    async def _generate_job(self, client: ManimaClient, prompt: Prompt) -> RunRecord:
        """Submit a prompt through ``generate_animation`` and persist the outcome."""

        t0 = time.perf_counter()
        handle = await client.generate_animation(prompt.prompt)
        enqueue_latency = time.perf_counter() - t0
        await self._poll_to_terminal(client, handle.job_id)
        result = await client.job_result(handle.job_id)
        total = time.perf_counter() - t0

        self.manima.observe_artifact(result.artifact_uri)
        return self.store.record_result(
            job_id=handle.job_id,
            prompt_id=prompt.id,
            tier=prompt.tier.value,
            condition=COND_APERTUS,
            profile=self.name,
            result=result,
            enqueue_latency_s=enqueue_latency,
            total_latency_s=total,
        )

    async def _render_job(
        self,
        client: ManimaClient,
        prompt: Prompt,
        source: str,
        condition: str,
    ) -> RunRecord:
        """Submit caller-supplied source through ``render_animation`` (control path)."""

        t0 = time.perf_counter()
        handle = await client.render_animation(source)
        enqueue_latency = time.perf_counter() - t0
        await self._poll_to_terminal(client, handle.job_id)
        result = await client.job_result(handle.job_id)
        total = time.perf_counter() - t0

        self.manima.observe_artifact(result.artifact_uri)
        return self.store.record_result(
            job_id=handle.job_id,
            prompt_id=prompt.id,
            tier=prompt.tier.value,
            condition=condition,
            profile=self.name,
            result=result,
            enqueue_latency_s=enqueue_latency,
            total_latency_s=total,
        )

    async def _poll_to_terminal(self, client: ManimaClient, job_id: str) -> JobStatus:
        """Poll ``job_status`` to a terminal state, recording every transition seen."""

        deadline = time.monotonic() + self.config.poll.timeout_s
        while True:
            status = await client.job_status(job_id)
            self.manima.observe_state(job_id, status.state)
            if status.state.terminal:
                return status
            if time.monotonic() >= deadline:
                from ..client import HarnessTimeout

                raise HarnessTimeout(
                    f"job {job_id} not terminal after {self.config.poll.timeout_s}s "
                    f"(last state {status.state.value})"
                )
            await anyio.sleep(self.config.poll.interval_s)

    def _drain_calls(self, client: ManimaClient) -> None:
        """Fold the client's timed calls into the MANIMA metrics (latency, contract)."""

        self.manima.observe_calls(client.calls)

    @asynccontextmanager
    async def _sampling(self) -> AsyncIterator[None]:
        """Tick the background side channels (Apertus + container count) for the run."""

        async with anyio.create_task_group() as tg:

            async def loop() -> None:
                while True:
                    now = time.monotonic()
                    self.apertus.sample(now)
                    self.manima.sample_containers(now)
                    await anyio.sleep(self.config.poll.interval_s)

            tg.start_soon(loop)
            try:
                yield
            finally:
                tg.cancel_scope.cancel()


def build_profile(name: str, **kwargs) -> Profile:
    """Instantiate a profile by name, raising a clear error on an unknown name."""

    from .burst import BurstProfile
    from .mixed import MixedProfile
    from .repair_heavy import RepairHeavyProfile
    from .soak import SoakProfile

    registry: dict[str, type[Profile]] = {
        SoakProfile.name: SoakProfile,
        BurstProfile.name: BurstProfile,
        RepairHeavyProfile.name: RepairHeavyProfile,
        MixedProfile.name: MixedProfile,
    }
    if name not in registry:
        raise KeyError(f"unknown profile {name!r}; known: {sorted(registry)}")
    return registry[name](**kwargs)


__all__ = [
    "Profile",
    "build_profile",
    "COND_APERTUS",
    "SourceGenerator",
]
