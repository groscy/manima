"""Server configuration.

One place for everything the server needs to run: sandbox limits, the escalation gate,
retention, and the endpoints of the WSL2-hosted dependencies (vLLM, Qdrant). Secrets are
never fields here — the escalation adapter reads its key from the environment (task 9.1),
so a config object can be logged without leaking anything.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SandboxLimits:
    """Per-container resource caps (specs/sandbox). Probe and full renders differ only in
    their wall-clock budget — a probe is a single 240p frame and must be quick."""

    memory: str = "2g"
    cpus: str = "2.0"
    probe_timeout_s: float = 30.0
    full_timeout_s: float = 300.0
    image: str = "manima-render:pinned"  # built from docker/Dockerfile
    # Container CLI: "docker" or "podman". Podman is daemonless and rootless-by-default,
    # which matches the project's rootless-container design (project.md, ADR-001).
    container_cli: str = "docker"
    # Rootless podman: map the container user to the host user so bind-mounted render
    # output is owned by (and readable to) the host. Ignored for docker.
    rootless_userns_keepid: bool = True
    # Apply --memory/--cpus/--pids-limit. Rootless podman needs cgroup-v2 delegation for
    # these; where that isn't set up, disable to let renders run without hard caps.
    enforce_resource_limits: bool = True


@dataclass(frozen=True)
class GenerateConfig:
    """Thick-path settings. Absent/unused on a render-only deployment (invariant 6)."""

    vllm_base_url: str = "http://localhost:8000/v1"
    vllm_model: str = "apertus-8b-int4"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "manim-ce"
    grounding_k: int = 8
    repair_budget: int = 3
    # Gate 1 of the escalation triple gate (ADR-003): the server-level permission.
    allow_escalation: bool = False
    escalation_model: str = "claude-opus-4-8"


@dataclass(frozen=True)
class ServerConfig:
    # WSL2 filesystem paths — never under /mnt/c (project.md, design D6/D7).
    store_root: Path = field(default_factory=lambda: Path.home() / ".manima" / "store")
    job_db_path: Path = field(default_factory=lambda: Path.home() / ".manima" / "jobs.db")
    artifact_ttl_s: float = 24 * 3600
    default_quality: str = "low"
    # Bound concurrent generations more tightly than renders: generation shares the GPU
    # with vLLM and a burst can OOM 16 GB (design D2).
    max_concurrent_generations: int = 1
    max_concurrent_renders: int = 3

    sandbox: SandboxLimits = field(default_factory=SandboxLimits)
    generate: GenerateConfig = field(default_factory=GenerateConfig)

    @staticmethod
    def from_env() -> "ServerConfig":
        """Overlay a few common env knobs; everything else takes the dataclass defaults."""

        cfg = ServerConfig()
        store = os.environ.get("MANIMA_STORE_ROOT")
        jobdb = os.environ.get("MANIMA_JOB_DB")
        gen = cfg.generate
        if os.environ.get("MANIMA_VLLM_URL"):
            gen = _replace(gen, vllm_base_url=os.environ["MANIMA_VLLM_URL"])
        if os.environ.get("MANIMA_ALLOW_ESCALATION") == "1":
            gen = _replace(gen, allow_escalation=True)
        sandbox = cfg.sandbox
        if os.environ.get("MANIMA_CONTAINER_CLI"):
            sandbox = _replace(sandbox, container_cli=os.environ["MANIMA_CONTAINER_CLI"])
        if os.environ.get("MANIMA_NO_RESOURCE_LIMITS") == "1":
            sandbox = _replace(sandbox, enforce_resource_limits=False)
        # Which image every render container is spawned from. Defaults to the locally-built
        # `manima-render:pinned`; point it at the published image (e.g.
        # ghcr.io/groscy/manima-render:pinned) to run from a pull instead of a local build.
        if os.environ.get("MANIMA_RENDER_IMAGE"):
            sandbox = _replace(sandbox, image=os.environ["MANIMA_RENDER_IMAGE"])
        return _replace(
            cfg,
            store_root=Path(store) if store else cfg.store_root,
            job_db_path=Path(jobdb) if jobdb else cfg.job_db_path,
            generate=gen,
            sandbox=sandbox,
        )


def _replace(obj, **changes):
    from dataclasses import replace

    return replace(obj, **changes)
