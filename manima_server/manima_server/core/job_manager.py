"""The async job manager (tasks 4.2-4.6, 5.x, 8.x, 9.x; design D2).

The spine of the server. Tools enqueue a job and get a ``job_id`` back immediately; the
manager advances it through the state machine on a background task, bounded by phase-aware
semaphores (generation is throttled harder than rendering — it shares the GPU with vLLM,
design D2). It orchestrates the ports and imports no adapter, so the whole thing is
testable with fakes.

It hosts both paths:
  - **render** (thin): validate -> render -> store. No generator, ever (invariant 6).
  - **generate** (thick): ground -> generate -> validate -> probe -> repair -> full, with
    deny-by-default escalation as the last resort.

Cancellation is cooperative: ``cancel`` flags the job and kills any running container; the
worker notices at its next checkpoint and transitions to ``CANCELLED``.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from ..config import ServerConfig
from . import state_machine as sm
from . import validator
from .domain import Attempt, Job, JobState, RenderMode, Tool
from .escalation import EscalationReceipt, should_escalate
from .ports import (
    AnimationGenerator,
    ArtifactStore,
    GroundingRetriever,
    JobStore,
    SandboxExecutor,
)


class JobManager:
    def __init__(
        self,
        config: ServerConfig,
        *,
        job_store: JobStore,
        sandbox: SandboxExecutor,
        artifact_store: ArtifactStore,
        generator: AnimationGenerator | None = None,
        grounding: GroundingRetriever | None = None,
        escalation_generator: AnimationGenerator | None = None,
    ) -> None:
        self._config = config
        self._jobs = job_store
        self._sandbox = sandbox
        self._store = artifact_store
        self._generator = generator
        self._grounding = grounding
        self._escalation = escalation_generator

        self._gen_sem = asyncio.Semaphore(config.max_concurrent_generations)
        self._render_sem = asyncio.Semaphore(config.max_concurrent_renders)
        self._tasks: dict[str, asyncio.Task] = {}
        self._cancelled: set[str] = set()
        self._containers: dict[str, str] = {}  # job_id -> active container name
        self.receipts: list[EscalationReceipt] = []

    # -- enqueue (returns within 2 s; the work runs in the background) -----------

    def submit_render(self, source: str, *, quality: str, scene_name: str | None) -> str:
        job = Job(
            job_id=_new_id(),
            tool=Tool.RENDER,
            params={"quality": quality, "scene_name": scene_name},
            source=source,
        )
        self._jobs.create(job)
        self._spawn(job, self._process_render(job))
        return job.job_id

    def submit_generate(
        self,
        prompt: str,
        *,
        quality: str,
        repair_budget: int,
        allow_escalation: bool,
    ) -> str:
        if self._generator is None or self._grounding is None:
            raise GenerateUnavailable(
                "generate_animation is not configured on this server (render-only deployment)"
            )
        job = Job(
            job_id=_new_id(),
            tool=Tool.GENERATE,
            params={
                "prompt": prompt,
                "quality": quality,
                "repair_budget": repair_budget,
                "allow_escalation": allow_escalation,
            },
        )
        self._jobs.create(job)
        self._spawn(job, self._process_generate(job))
        return job.job_id

    # -- observe ----------------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        return self._jobs.load(job_id)

    async def cancel(self, job_id: str) -> dict:
        job = self._jobs.load(job_id)
        if job is None:
            return {"job_id": job_id, "cancelled": False, "reason": "unknown job"}
        if job.state.terminal:
            # Cancelling a terminal job is a no-op that acknowledges as such (specs/jobs).
            return {"job_id": job_id, "cancelled": False, "already_terminal": True}
        self._cancelled.add(job_id)
        container = self._containers.get(job_id)
        if container is not None:
            await self._sandbox.kill(container)
        return {"job_id": job_id, "cancelled": True}

    async def wait(self, job_id: str) -> None:
        """Await a job's background task (used by tests and graceful shutdown)."""

        task = self._tasks.get(job_id)
        if task is not None:
            await asyncio.shield(task)

    # -- render path (thin) -----------------------------------------------------

    async def _process_render(self, job: Job) -> None:
        async with self._render_sem:
            if self._check_cancel(job):
                return
            source = job.source or ""
            quality = job.params["quality"]
            scene_name = job.params["scene_name"]

            # Cache: an identical request resolves without re-rendering (specs/render).
            key = self._store.key_for(source, quality)
            cached = self._store.get(key)

            self._transition(job, JobState.VALIDATING, phase="validating")
            vr = validator.validate(source)
            if not vr.ok:
                self._fail(job, vr.as_repair_message(), source=source)
                return
            resolved = self._resolve_scene(job, source, scene_name)
            if resolved is _AMBIGUOUS:
                return  # _resolve_scene already failed the job

            self._transition(job, JobState.RENDERING, phase="rendering")
            if cached is not None:
                self._succeed(job, cached, source=source, generator=None)
                return
            if self._check_cancel(job):
                return
            outcome = await self._render(job, source, resolved, quality, RenderMode.FULL)
            job.add_attempt(Attempt(0, generator=None, source=source, traceback=outcome.traceback))
            if self._check_cancel(job):
                return
            if outcome.ok and outcome.artifact_path:
                uri = self._store.put(key, outcome.artifact_path)
                self._succeed(job, uri, source=source, generator=None)
            else:
                self._fail(job, outcome.traceback or "render failed", source=source)

    # -- generate path (thick) --------------------------------------------------

    async def _process_generate(self, job: Job) -> None:
        async with self._gen_sem:
            if self._check_cancel(job):
                return
            prompt = job.params["prompt"]
            quality = job.params["quality"]
            budget = int(job.params["repair_budget"])
            allow_escalation = bool(job.params["allow_escalation"])

            grounding = await self._grounding.retrieve(prompt, self._config.generate.grounding_k)

            repair_source: str | None = None
            repair_traceback: str | None = None

            # Bounded local attempts (specs/generate: attempts bounded by repair_budget).
            for index in range(max(1, budget)):
                if self._check_cancel(job):
                    return
                self._transition(job, JobState.GENERATING, phase=f"generating (attempt {index + 1})")
                source = await self._generator.generate(
                    prompt, grounding=grounding,
                    repair_source=repair_source, repair_traceback=repair_traceback,
                )
                outcome_tb = await self._attempt_candidate(
                    job, index, source, quality, self._generator.identity, escalated=False
                )
                if outcome_tb is None:
                    return  # succeeded (or cancelled) inside _attempt_candidate
                repair_source, repair_traceback = source, outcome_tb

            # Local budget exhausted. Escalate iff all three gates are open (ADR-003).
            if should_escalate(
                config_permits=self._config.generate.allow_escalation,
                call_allows=allow_escalation,
                budget_exhausted=True,
            ) and self._escalation is not None:
                if self._check_cancel(job):
                    return
                self._transition(job, JobState.GENERATING, phase="generating (escalated)")
                source = await self._escalation.generate(
                    prompt, grounding=grounding,
                    repair_source=repair_source, repair_traceback=repair_traceback,
                )
                self.receipts.append(
                    EscalationReceipt(
                        job_id=job.job_id, model=self._escalation.identity,
                        input_tokens=None, output_tokens=None,
                        reason="local repair budget exhausted",
                    )
                )
                job.escalated = True
                if await self._attempt_candidate(
                    job, budget, source, quality, self._escalation.identity, escalated=True
                ) is None:
                    return

            # Everything failed with escalation closed or also failing: FAILED with the
            # last traceback and best-effort source (specs/generate).
            self._fail(job, job.last_traceback or "generation failed", source=job.best_effort_source)

    async def _attempt_candidate(
        self, job: Job, index: int, source: str, quality: str, generator: str, *, escalated: bool
    ) -> str | None:
        """Validate -> probe -> full for one candidate.

        Returns None on success (job is now SUCCEEDED, or CANCELLED) — the caller stops.
        Returns the traceback string on failure — the caller repairs with it.
        """

        self._transition(job, JobState.VALIDATING, phase="validating")
        vr = validator.validate(source)
        if not vr.ok:
            job.add_attempt(Attempt(index, generator, source, vr.as_repair_message(), escalated))
            return vr.as_repair_message()

        # Probe: 240p single frame in the sandbox — the mechanical oracle.
        self._transition(job, JobState.RENDERING, phase="probe")
        if self._check_cancel(job):
            return None
        probe = await self._render(job, source, None, quality, RenderMode.PROBE)
        if not probe.ok:
            job.add_attempt(Attempt(index, generator, source, probe.traceback, escalated))
            return probe.traceback or "probe render failed"

        # Probe passed -> full quality. We verified it runs, not that it is correct.
        if self._check_cancel(job):
            return None
        full = await self._render(job, source, None, quality, RenderMode.FULL)
        job.add_attempt(Attempt(index, generator, source, full.traceback, escalated))
        if self._check_cancel(job):
            return None
        if full.ok and full.artifact_path:
            key = self._store.key_for(source, quality)
            uri = self._store.put(key, full.artifact_path)
            self._succeed(job, uri, source=source, generator=generator)
            return None
        return full.traceback or "full render failed"

    # -- shared helpers ---------------------------------------------------------

    async def _render(self, job, source, scene_name, quality, mode: RenderMode):
        container = f"manima-{job.job_id}-{mode.value}"
        self._containers[job.job_id] = container
        try:
            return await self._sandbox.run(
                source, mode=mode, scene_name=scene_name, quality=quality, name=container
            )
        finally:
            self._containers.pop(job.job_id, None)

    def _resolve_scene(self, job: Job, source: str, scene_name: str | None):
        if scene_name is not None:
            return scene_name
        scenes = validator.scene_names(source)
        if len(scenes) > 1:
            self._fail(
                job,
                f"ambiguous scene: multiple Scene subclasses found ({', '.join(scenes)}); "
                "pass scene_name",
                source=source,
            )
            return _AMBIGUOUS
        return scenes[0] if scenes else None

    def _transition(self, job: Job, new_state: JobState, *, phase: str | None = None) -> None:
        sm.assert_transition(job.state, new_state)
        job.state = new_state
        job.phase = phase
        job.touch()
        self._jobs.save(job)

    def _succeed(self, job: Job, artifact_uri: str, *, source: str | None, generator: str | None) -> None:
        job.artifact_uri = artifact_uri
        job.source = source
        job.expires_at = time.time() + self._config.artifact_ttl_s
        self._transition(job, JobState.SUCCEEDED, phase="done")

    def _fail(self, job: Job, error: str, *, source: str | None = None) -> None:
        job.error = error
        if source is not None:
            job.source = source
        job.expires_at = time.time() + self._config.artifact_ttl_s
        self._transition(job, JobState.FAILED, phase="failed")

    def _check_cancel(self, job: Job) -> bool:
        if job.job_id in self._cancelled and not job.state.terminal:
            self._transition(job, JobState.CANCELLED, phase="cancelled")
            return True
        return job.state.terminal

    def _spawn(self, job: Job, coro) -> None:
        task = asyncio.ensure_future(self._guard(job, coro))
        self._tasks[job.job_id] = task

    async def _guard(self, job: Job, coro) -> None:
        """Run a job coroutine; any unexpected error fails the job rather than vanishing."""

        try:
            await coro
        except Exception as exc:  # noqa: BLE001 - a worker crash must not be silent
            fresh = self._jobs.load(job.job_id) or job
            if not fresh.state.terminal:
                fresh.error = f"internal error: {exc!r}"
                fresh.state = JobState.FAILED
                fresh.touch()
                self._jobs.save(fresh)


_AMBIGUOUS = object()


def _new_id() -> str:
    return uuid.uuid4().hex


class GenerateUnavailable(RuntimeError):
    """generate_animation was called on a render-only deployment."""
