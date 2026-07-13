"""Filesystem-backed content-addressed artifact store (tasks 3.1-3.3, specs/render).

Artifacts live on the WSL2 filesystem (design D6 — never under ``/mnt/c``, where
multi-megabyte video I/O is slow). The key is the content hash of
``(source, quality, manim_version)``, so an identical request is a cache hit and a version
bump never collides. Artifacts are always referenced by path — bytes are never inlined
(invariant 4).
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from ..core.hashing import content_key
from ..version import MANIM_CE_VERSION


class FsArtifactStore:
    """`ArtifactStore` adapter over a directory tree keyed by content hash."""

    def __init__(
        self,
        root: Path,
        ttl_s: float,
        *,
        manim_version: str = MANIM_CE_VERSION,
    ) -> None:
        self.root = Path(root)
        self.ttl_s = ttl_s
        self.manim_version = manim_version
        self.root.mkdir(parents=True, exist_ok=True)

    def key_for(self, source: str, quality: str) -> str:
        return content_key(source, quality, self.manim_version)

    def _path(self, key: str) -> Path:
        # Shard by the first two hex chars to keep any one directory small.
        return self.root / key[:2] / f"{key}.mp4"

    def get(self, key: str) -> str | None:
        path = self._path(key)
        return str(path) if path.exists() else None

    def put(self, key: str, artifact_path: str) -> str:
        """Copy the rendered video into the store under its content key.

        Idempotent: a second put of the same key is a no-op that returns the existing
        path — the cache-hit case never re-renders (specs/render).
        """

        dst = self._path(key)
        if dst.exists():
            return str(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Copy into a temp name then atomically replace, so a crash mid-copy never leaves
        # a truncated artifact under a valid key.
        tmp = dst.with_suffix(".mp4.partial")
        shutil.copyfile(artifact_path, tmp)
        tmp.replace(dst)
        return str(dst)

    def reap(self) -> list[str]:
        """Remove artifacts older than the TTL; return the reaped keys (task 11.1).

        The job-side consequence (transition to ``EXPIRED``) is the reaper's job in the
        job manager; the store only owns the bytes.
        """

        now = time.time()
        reaped: list[str] = []
        for path in self.root.rglob("*.mp4"):
            if now - path.stat().st_mtime > self.ttl_s:
                reaped.append(path.stem)
                path.unlink(missing_ok=True)
        return reaped
