"""MCP stdio server assembly (tasks 10.1-10.3, specs/*).

Wires config -> adapters -> job manager and exposes the five tools over stdio. The
assembly order encodes the invariants:

  - The sandbox is built and **preflighted first**; if Docker is unreachable or the render
    image is missing, the server refuses to start, loudly, with no host fallback (2.5, 10.2).
  - The render path is always wired. The generate-path adapters (vLLM, Qdrant, escalation)
    are wired only if configured; absent them, ``generate_animation`` reports unavailable
    and ``render_animation`` is fully functional (invariant 6).

Tools do no work beyond enqueue/observe, so every call returns well within 2 s regardless
of render duration (10.3) — the job manager does the slow work on a background task.
"""

from __future__ import annotations

import os

from .config import ServerConfig
from .core.domain import Job, JobState
from .core.job_manager import GenerateUnavailable, JobManager
from .core.reaper import Reaper


def build_manager(config: ServerConfig) -> tuple[JobManager, Reaper]:
    """Construct adapters and the job manager. Runs the sandbox preflight (fail-loud)."""

    from .adapters.docker_sandbox import DockerSandbox
    from .adapters.fs_store import FsArtifactStore
    from .adapters.sqlite_jobs import SqliteJobStore

    sandbox = DockerSandbox(config.sandbox)
    sandbox.preflight()  # 10.2 / 2.5 — raises SandboxUnavailable -> server won't start

    store = FsArtifactStore(config.store_root, config.artifact_ttl_s)
    jobs = SqliteJobStore(config.job_db_path)

    generator = grounding = escalation = None
    if _generate_configured():
        from .adapters.qdrant_grounding import QdrantGrounding
        from .adapters.vllm_generator import ApertusVLLMGenerator

        generator = ApertusVLLMGenerator(
            config.generate.vllm_base_url, config.generate.vllm_model
        )
        grounding = QdrantGrounding(
            config.generate.qdrant_url, config.generate.qdrant_collection
        )
        # Escalation is only constructed if the server-level gate is open (gate 1). With
        # it shut, the hosted-model SDK is never even imported.
        if config.generate.allow_escalation:
            from .adapters.escalation_generator import AnthropicEscalationGenerator

            escalation = AnthropicEscalationGenerator(config.generate.escalation_model)

    manager = JobManager(
        config,
        job_store=jobs,
        sandbox=sandbox,
        artifact_store=store,
        generator=generator,
        grounding=grounding,
        escalation_generator=escalation,
    )
    return manager, Reaper(jobs, store)


def create_app(config: ServerConfig | None = None):
    """Build the FastMCP app with the five tools bound to a job manager."""

    from mcp.server.fastmcp import FastMCP

    config = config or ServerConfig.from_env()
    manager, reaper = build_manager(config)
    mcp = FastMCP("manima")

    @mcp.tool()
    async def render_animation(
        source: str, quality: str | None = None, scene_name: str | None = None
    ) -> dict:
        """Render caller-supplied Manim CE source. Returns a job_id immediately."""

        job_id = manager.submit_render(
            source, quality=quality or config.default_quality, scene_name=scene_name
        )
        return {"job_id": job_id}

    @mcp.tool()
    async def generate_animation(
        prompt: str,
        quality: str | None = None,
        repair_budget: int | None = None,
        allow_escalation: bool = False,
    ) -> dict:
        """Generate + verify a Manim CE scene locally. Returns a job_id immediately."""

        try:
            job_id = manager.submit_generate(
                prompt,
                quality=quality or config.default_quality,
                repair_budget=repair_budget
                if repair_budget is not None
                else config.generate.repair_budget,
                allow_escalation=allow_escalation,
            )
        except GenerateUnavailable as exc:
            return {"error": str(exc)}
        return {"job_id": job_id}

    @mcp.tool()
    async def job_status(job_id: str) -> dict:
        """Cheap, non-blocking: state, attempt, phase."""

        job = manager.get(job_id)
        if job is None:
            return {"error": f"unknown job {job_id}"}
        return {"state": job.state.value, "attempt": job.attempt, "phase": job.phase}

    @mcp.tool()
    async def job_result(job_id: str) -> dict:
        """Valid only in terminal states: artifact_uri, source, trace."""

        job = manager.get(job_id)
        if job is None:
            return {"error": f"unknown job {job_id}"}
        if not job.state.terminal:
            return {"state": job.state.value, "error": "job is not in a terminal state"}
        return _result_payload(job)

    @mcp.tool()
    async def cancel_job(job_id: str) -> dict:
        """Kill a running job; no-op on an already-terminal one."""

        return await manager.cancel(job_id)

    return mcp, manager, reaper


def _result_payload(job: Job) -> dict:
    if job.state is JobState.EXPIRED:
        # 11.2 — report expiry, not a dangling path.
        return {"state": job.state.value, "expired": True,
                "message": "artifact and logs were reaped past their retention window"}
    return {
        "state": job.state.value,
        "artifact_uri": job.artifact_uri,
        "source": job.source,
        "error": job.error,
        "escalated": job.escalated,
        # The full attempt trace — per-attempt source + traceback — so a client (e.g. the
        # load-test harness) can persist every attempt for taxonomy (specs/jobs).
        "trace": [
            {
                "index": a.index,
                "generator": a.generator,
                "source": a.source,
                "traceback": a.traceback,
                "escalated": a.escalated,
            }
            for a in job.trace
        ],
    }


def _generate_configured() -> bool:
    """Generate is on unless explicitly disabled. A render-only box sets MANIMA_RENDER_ONLY=1."""

    return os.environ.get("MANIMA_RENDER_ONLY") != "1"


def main() -> None:
    """Console entrypoint: build the app, start the reaper, serve stdio."""

    import anyio

    config = ServerConfig.from_env()
    mcp, manager, reaper = create_app(config)

    async def _reaper_loop() -> None:
        while True:
            await anyio.sleep(min(3600.0, config.artifact_ttl_s))
            reaper.reap(_now())

    # FastMCP owns the event loop; register the reaper as a background task via its
    # startup hook if available, else rely on the run loop. Kept simple here — the reaper
    # is idempotent, so a missed tick only delays expiry.
    async def _serve() -> None:
        async with anyio.create_task_group() as tg:
            tg.start_soon(_reaper_loop)
            await mcp.run_stdio_async()

    anyio.run(_serve)


def _now() -> float:
    import time

    return time.time()


if __name__ == "__main__":
    main()
