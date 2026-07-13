#!/usr/bin/env python3
"""Deployment smoke test (tasks 4.1-4.2, deployment spec).

Prove a render-only deployment actually renders — "started" is not "healthy"
(invariant 3). Spawns the MANIMA server over stdio exactly as any MCP client would,
submits a trivial scene through ``render_animation``, polls to a terminal state, and
asserts SUCCEEDED with a retrievable artifact.

Exit codes:
  0  the scene reached SUCCEEDED and ``job_result`` returned an ``artifact_uri``.
  1  anything else — a FAILED/EXPIRED job, a missing artifact, or (importantly) a
     server that would not even start because the sandbox is misconfigured (e.g. the
     Docker daemon is unreachable). A broken deployment fails loudly, non-zero (4.2).

Run via ``make smoke``, or directly:
    MANIMA_RENDER_ONLY=1 python manima_server/scripts/smoke_render.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# A trivial scene: one Circle. Exercises Manim + the sandbox end to end without LaTeX or
# 3D. Deliberately boring — this checks the pipeline, not Manim's features.
SMOKE_SOURCE = """
from manim import Scene, Circle, Create


class Smoke(Scene):
    def construct(self):
        self.play(Create(Circle()))
"""

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"}
POLL_INTERVAL_S = 1.0
POLL_TIMEOUT_S = 300.0  # the sandbox's full-render budget; a harness timeout is itself a bug

# manima_server/ — putting it on cwd lets `python -m manima_server.server` resolve the
# package without an editable install having been run first.
SERVER_DIR = Path(__file__).resolve().parents[1]


def _payload(result) -> dict:
    """Extract a tool call's dict payload from structuredContent or text blocks."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        # Some SDK versions wrap a bare dict return under a "result" key.
        return structured.get("result", structured)
    content = getattr(result, "content", None) or []
    text = "".join(getattr(block, "text", "") or "" for block in content)
    return json.loads(text) if text else {}


async def _run() -> int:
    env = dict(os.environ)
    env["MANIMA_RENDER_ONLY"] = "1"  # never wire the generate path for a smoke render
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "manima_server.server"],
        env=env,
        cwd=str(SERVER_DIR),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            submit = _payload(
                await session.call_tool("render_animation", {"source": SMOKE_SOURCE})
            )
            job_id = submit.get("job_id")
            if not job_id:
                print(f"SMOKE FAIL: render_animation returned no job_id: {submit!r}")
                return 1
            print(f"submitted render job {job_id}; polling to terminal...")

            deadline = time.monotonic() + POLL_TIMEOUT_S
            state = None
            while True:
                status = _payload(
                    await session.call_tool("job_status", {"job_id": job_id})
                )
                state = status.get("state")
                if state in TERMINAL:
                    break
                if time.monotonic() >= deadline:
                    print(
                        f"SMOKE FAIL: job {job_id} not terminal after "
                        f"{POLL_TIMEOUT_S:.0f}s (last state {state})"
                    )
                    return 1
                await asyncio.sleep(POLL_INTERVAL_S)

            result = _payload(
                await session.call_tool("job_result", {"job_id": job_id})
            )
            if state != "SUCCEEDED":
                print(
                    f"SMOKE FAIL: job {job_id} terminal in {state}, not SUCCEEDED. "
                    f"trace={result.get('trace')!r}"
                )
                return 1
            artifact = result.get("artifact_uri")
            if not artifact:
                print(f"SMOKE FAIL: SUCCEEDED but no artifact_uri: {result!r}")
                return 1
            print(f"SMOKE OK: job {job_id} SUCCEEDED — artifact at {artifact}")
            return 0


def main() -> int:
    try:
        return asyncio.run(_run())
    except Exception as exc:
        # A server that won't start (Docker unreachable -> SandboxUnavailable at preflight)
        # surfaces here as a failed stdio init. That IS the signal: a broken deployment is
        # not healthy (task 4.2). Fail loudly, non-zero, on ANY error.
        print(f"SMOKE FAIL: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
