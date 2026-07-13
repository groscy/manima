"""Harness configuration.

The harness is Windows-native; the MANIMA server lives in WSL2 (project.md,
"Platform notes"). So the stdio launch command is not fixed — on Windows it is
typically ``wsl.exe -d <distro> -- <server entrypoint>``, on a Linux dev box it is
the entrypoint directly. Everything the harness needs to reach the server, and how
hard to push it, is captured here rather than hard-coded at the call sites.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ServerLaunch:
    """How to spawn the MANIMA MCP server as a stdio subprocess."""

    command: str = "wsl.exe"
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    # Working directory for the spawned server, if it must differ from the harness.
    cwd: str | None = None


@dataclass(frozen=True)
class PollConfig:
    """How the client polls a job to a terminal state.

    ``job_status`` is documented as cheap and non-blocking, so polling is the right
    shape. The interval is a client-side choice; keep it small enough that latency
    percentiles (instrument.ManimaMetrics) stay meaningful.
    """

    interval_s: float = 0.25
    # Hard ceiling so a wedged server can't hang a profile forever. This is a harness
    # safety net, not the sandbox timeout (that is MANIMA's, per specs/sandbox).
    timeout_s: float = 900.0


@dataclass(frozen=True)
class HarnessConfig:
    server: ServerLaunch = field(default_factory=ServerLaunch)
    poll: PollConfig = field(default_factory=PollConfig)

    # Default render/generate quality for profiles that don't override it.
    quality: str = "low"
    # generate_animation repair budget (specs/generate default is 3). Exposed so the
    # repair-heavy profile and the "cut the budget to 1" finding (task 6.3) are
    # experiments, not code edits.
    repair_budget: int = 3
    # Escalation stays deny-by-default (ADR-003). The harness never flips this on
    # implicitly; a control run that wants the frontier path uses the frontier
    # generator directly (section 3), not server-side escalation.
    allow_escalation: bool = False

    # Where per-attempt raw source + tracebacks and metrics land (task 2.6).
    out_dir: Path = field(default_factory=lambda: Path("runs"))

    @staticmethod
    def load(path: str | os.PathLike[str] | None) -> "HarnessConfig":
        """Load config from a JSON file, overlaying env for the launch command.

        Env overrides (handy on CI / WSL): ``MANIMA_SERVER_COMMAND`` and
        ``MANIMA_SERVER_ARGS`` (whitespace-split).
        """

        cfg = HarnessConfig()
        if path is not None:
            data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
            cfg = _apply_overrides(cfg, data)

        command = os.environ.get("MANIMA_SERVER_COMMAND")
        args = os.environ.get("MANIMA_SERVER_ARGS")
        if command or args:
            server = cfg.server
            if command:
                server = replace(server, command=command)
            if args:
                server = replace(server, args=tuple(args.split()))
            cfg = replace(cfg, server=server)
        return cfg


def _apply_overrides(cfg: HarnessConfig, data: dict[str, Any]) -> HarnessConfig:
    server = cfg.server
    if "server" in data:
        s = data["server"]
        server = ServerLaunch(
            command=s.get("command", server.command),
            args=tuple(s.get("args", server.args)),
            env=dict(s.get("env", server.env)),
            cwd=s.get("cwd", server.cwd),
        )
    poll = cfg.poll
    if "poll" in data:
        p = data["poll"]
        poll = PollConfig(
            interval_s=float(p.get("interval_s", poll.interval_s)),
            timeout_s=float(p.get("timeout_s", poll.timeout_s)),
        )
    return replace(
        cfg,
        server=server,
        poll=poll,
        quality=data.get("quality", cfg.quality),
        repair_budget=int(data.get("repair_budget", cfg.repair_budget)),
        allow_escalation=bool(data.get("allow_escalation", cfg.allow_escalation)),
        out_dir=Path(data.get("out_dir", cfg.out_dir)),
    )
