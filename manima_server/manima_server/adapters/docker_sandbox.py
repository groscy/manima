"""Docker sandbox executor (tasks 2.2-2.5, specs/sandbox).

One rootless container per render, torn down after. The security posture is applied on
every path — there is no bypass flag and no host-execution fallback (invariants 1 & 5):

  --network=none              no egress; a socket/DNS attempt fails as a render traceback
  --cap-drop=ALL              drop all Linux capabilities
  --security-opt no-new-privileges
  --read-only                 read-only root filesystem; scratch is tmpfs / the bind mount
  --user 1000:1000            non-root (the image also sets USER manim)
  --memory / --memory-swap    memory cap with swap disabled so exhaustion OOM-kills
  --cpus / --pids-limit       CPU quota and a fork-bomb bound
  seccomp                     Docker's default restricted profile (or an operator's)

Probe and full renders carry separate wall-clock budgets (task 2.3). A timeout kills the
container; the job that owns it fails while the server and other jobs stay responsive
(task 2.4). This adapter is written against the Docker CLI; it cannot be runtime-verified
without a reachable Docker daemon, which is exactly what ``preflight`` guards.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from ..config import SandboxLimits
from ..core.domain import RenderMode, RenderOutcome

# Manim CE quality flags.
_QUALITY_FLAG = {"low": "-ql", "medium": "-qm", "high": "-qh"}
# Probe resolution: 240p. A single last-frame render is a cheap syntax/API oracle.
_PROBE_RES = "426,240"


class DockerSandbox:
    """`SandboxExecutor` adapter driving `docker run`."""

    def __init__(self, limits: SandboxLimits, *, seccomp_profile: str | None = None) -> None:
        self._limits = limits
        self._seccomp = seccomp_profile

    def preflight(self) -> None:
        """Fail loud if the Docker daemon is unreachable or the image is missing (2.5).

        Synchronous and called at startup, before the server accepts a single call. There
        is deliberately no fallback: if this raises, the server must not start."""

        if shutil.which("docker") is None:
            raise SandboxUnavailable("docker CLI not found on PATH")
        try:
            proc = _run_sync(["docker", "info", "--format", "{{.ServerVersion}}"])
        except OSError as exc:  # pragma: no cover - environment dependent
            raise SandboxUnavailable(f"cannot exec docker: {exc}") from exc
        if proc.returncode != 0:
            raise SandboxUnavailable(
                f"docker daemon unreachable: {proc.stderr.strip() or 'docker info failed'}"
            )
        img = _run_sync(["docker", "image", "inspect", self._limits.image])
        if img.returncode != 0:
            raise SandboxUnavailable(
                f"render image '{self._limits.image}' not present; build docker/Dockerfile"
            )

    async def kill(self, name: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "docker", "kill", name,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()  # already-gone container -> non-zero, which is fine

    async def run(
        self,
        source: str,
        *,
        mode: RenderMode,
        scene_name: str | None = None,
        quality: str = "low",
        name: str | None = None,
    ) -> RenderOutcome:
        timeout = (
            self._limits.probe_timeout_s
            if mode is RenderMode.PROBE
            else self._limits.full_timeout_s
        )
        container = name or f"manima-{mode.value}-{_short_id()}"

        # A per-render working dir on the WSL2 filesystem, bind-mounted as writable /work.
        work = Path(tempfile.mkdtemp(prefix="manima-"))
        try:
            (work / "scene.py").write_text(source, encoding="utf-8")
            cmd = self._docker_cmd(work, container, mode, quality, scene_name)

            loop = asyncio.get_event_loop()
            start = loop.time()
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout)
            except asyncio.TimeoutError:
                await self.kill(container)
                await proc.wait()
                return RenderOutcome(
                    ok=False, mode=mode, timed_out=True,
                    duration_s=timeout,
                    traceback=f"wall-clock timeout after {timeout}s ({mode.value} budget)",
                )

            duration = loop.time() - start
            stderr = stderr_b.decode("utf-8", "replace")
            if proc.returncode == 0:
                artifact = _find_output(work, mode)
                return RenderOutcome(
                    ok=artifact is not None, mode=mode,
                    artifact_path=str(artifact) if artifact else None,
                    duration_s=duration,
                    traceback=None if artifact else "render exited 0 but produced no artifact",
                )
            # Non-zero: exit 137 without a timeout is the OOM-kill signature (memory cap).
            oom = proc.returncode == 137
            return RenderOutcome(
                ok=False, mode=mode, oom=oom, duration_s=duration,
                traceback=stderr or f"render exited {proc.returncode}",
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _docker_cmd(
        self,
        work: Path,
        container: str,
        mode: RenderMode,
        quality: str,
        scene_name: str | None,
    ) -> list[str]:
        cmd = [
            "docker", "run", "--rm", "--name", container,
            "--network=none",
            "--cap-drop=ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",
            "--user", "1000:1000",
            "--memory", self._limits.memory,
            "--memory-swap", self._limits.memory,  # == memory => swap disabled
            "--cpus", self._limits.cpus,
            "--pids-limit", "256",
            # Writable scratch on a read-only rootfs.
            "--tmpfs", "/tmp:rw,nosuid,nodev",
            "-v", f"{work}:/work",
            "-w", "/work",
            "-e", "HOME=/work",
            "-e", "TEXMFVAR=/tmp/texmf-var",
            "-e", "XDG_CACHE_HOME=/work/.cache",
        ]
        if self._seccomp:
            cmd += ["--security-opt", f"seccomp={self._seccomp}"]
        cmd.append(self._limits.image)

        # Manim argument vector (image ENTRYPOINT is `manim`).
        cmd += ["--media_dir", "/work/media", "--disable_caching"]
        if mode is RenderMode.PROBE:
            cmd += ["-s", "-r", _PROBE_RES]  # save last frame at 240p
        else:
            cmd.append(_QUALITY_FLAG.get(quality, "-ql"))
        cmd.append("/work/scene.py")
        if scene_name:
            cmd.append(scene_name)
        return cmd


def _find_output(work: Path, mode: RenderMode) -> Path | None:
    media = work / "media"
    if not media.exists():
        return None
    pattern = "*.png" if mode is RenderMode.PROBE else "*.mp4"
    # Newest match wins, in case caching produced more than one.
    candidates = sorted(media.rglob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _short_id() -> str:
    import uuid

    return uuid.uuid4().hex[:8]


def _run_sync(cmd: list[str]):
    import subprocess

    return subprocess.run(cmd, capture_output=True, text=True, timeout=10)


class SandboxUnavailable(RuntimeError):
    """The sandbox cannot operate — the server must refuse to start (specs/sandbox)."""
