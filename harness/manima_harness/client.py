"""The MCP client that drives MANIMA.

"An ordinary client. No privileged access, no special endpoints, no hooks into
server internals" (proposal.md). This wraps the ``mcp`` stdio client with exactly the
five documented tools and a poll-to-terminal helper, and it times every call so the
instrumentation layer can assert the async contract (task 4.3: tool calls stay under
2 s at every concurrency level).

The client cannot be exercised until a MANIMA server exists to spawn. It is written
against ``specs/`` and ``mcp`` SDK signatures; the ASSUMPTION markers in ``contract``
flag the wire details a real server will confirm or refute.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import HarnessConfig
from .contract import (
    TOOL_CANCEL,
    TOOL_GENERATE,
    TOOL_JOB_RESULT,
    TOOL_JOB_STATUS,
    TOOL_RENDER,
    JobHandle,
    JobResult,
    JobStatus,
    TimedCall,
    parse_job_handle,
    parse_job_result,
    parse_job_status,
    payload_from_tool_result,
)


class ManimaClient:
    """Async wrapper over one MCP session.

    Instances are cheap; open one per worker so concurrent profiles get independent
    sessions rather than serialising on a shared lock.
    """

    def __init__(self, session: ClientSession, config: HarnessConfig) -> None:
        self._session = session
        self._config = config
        # Every tool-call latency, in call order — drained by ManimaMetrics.
        self.calls: list[TimedCall] = []

    # -- enqueue tools ----------------------------------------------------------

    async def render_animation(
        self,
        source: str,
        *,
        quality: str | None = None,
        scene_name: str | None = None,
    ) -> JobHandle:
        args: dict[str, Any] = {"source": source, "quality": quality or self._config.quality}
        if scene_name is not None:
            args["scene_name"] = scene_name
        payload = await self._call(TOOL_RENDER, args)
        return parse_job_handle(payload)

    async def generate_animation(
        self,
        prompt: str,
        *,
        quality: str | None = None,
        repair_budget: int | None = None,
        allow_escalation: bool | None = None,
    ) -> JobHandle:
        args: dict[str, Any] = {
            "prompt": prompt,
            "quality": quality or self._config.quality,
            "repair_budget": self._config.repair_budget
            if repair_budget is None
            else repair_budget,
            "allow_escalation": self._config.allow_escalation
            if allow_escalation is None
            else allow_escalation,
        }
        payload = await self._call(TOOL_GENERATE, args)
        return parse_job_handle(payload)

    # -- job tools --------------------------------------------------------------

    async def job_status(self, job_id: str) -> JobStatus:
        payload = await self._call(TOOL_JOB_STATUS, {"job_id": job_id})
        return parse_job_status(payload)

    async def job_result(self, job_id: str) -> JobResult:
        payload = await self._call(TOOL_JOB_RESULT, {"job_id": job_id})
        return parse_job_result(payload)

    async def cancel_job(self, job_id: str) -> dict[str, Any]:
        return await self._call(TOOL_CANCEL, {"job_id": job_id})

    # -- composed: enqueue + poll to terminal -----------------------------------

    async def await_terminal(self, job_id: str) -> JobStatus:
        """Poll ``job_status`` until the job reaches a terminal state or we time out.

        Uses a wall-clock deadline as a harness safety net; the *real* timeout is the
        sandbox's (specs/sandbox). A harness timeout is itself a finding — the server
        should have driven the job to FAILED long before this fires.
        """

        import anyio  # local import: only needed on this path

        deadline = time.monotonic() + self._config.poll.timeout_s
        while True:
            status = await self.job_status(job_id)
            if status.state.terminal:
                return status
            if time.monotonic() >= deadline:
                raise HarnessTimeout(
                    f"job {job_id} not terminal after "
                    f"{self._config.poll.timeout_s}s (last state {status.state.value})"
                )
            await anyio.sleep(self._config.poll.interval_s)

    # -- internals --------------------------------------------------------------

    async def _call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        result = await self._session.call_tool(tool, args)
        latency = time.perf_counter() - start

        text = _text_of(result)
        structured = getattr(result, "structuredContent", None)
        if getattr(result, "isError", False):
            # An MCP-level error is distinct from a job FAILED. Surface it verbatim.
            raise ToolCallError(f"{tool} returned isError: {text!r}")
        payload = payload_from_tool_result(structured, text)
        self.calls.append(TimedCall(tool=tool, latency_s=latency, payload=payload))
        return payload


@asynccontextmanager
async def connect(config: HarnessConfig) -> AsyncIterator[ManimaClient]:
    """Spawn the MANIMA server over stdio and yield a ready client.

    On Windows the launch command is typically ``wsl.exe -d <distro> -- <entrypoint>``
    (project.md). ``config.server`` supplies command, args, env, and cwd.
    """

    params = StdioServerParameters(
        command=config.server.command,
        args=list(config.server.args),
        env=config.server.env or None,
        cwd=config.server.cwd,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield ManimaClient(session, config)


def _text_of(result: Any) -> str | None:
    """Concatenate text content blocks from a CallToolResult."""

    content = getattr(result, "content", None) or []
    parts = [getattr(block, "text", None) for block in content]
    text = "".join(p for p in parts if p)
    return text or None


class ToolCallError(RuntimeError):
    """The MCP layer flagged the call itself as an error (not a job FAILED)."""


class HarnessTimeout(RuntimeError):
    """A job never reached a terminal state within the harness safety deadline."""
