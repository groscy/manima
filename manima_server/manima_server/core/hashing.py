"""Content-addressing (specs/render, design D6).

The artifact key is a hash of ``(source, quality, manim_version)``. Two properties fall
out of including all three:

  - **Cache hits**: identical source at identical quality resolves to the same key, so a
    repeat request is served from the store without re-rendering.
  - **No cross-version collisions**: because ``manim_version`` participates in the hash, a
    version bump cannot alias a new render onto a stale artifact.

Pure and deterministic — no I/O — so it is unit-testable and safe to call from both the
store adapter and the pipeline. The Manim version comes from the single pin in
``version.MANIM_CE_VERSION`` (design D8).
"""

from __future__ import annotations

import hashlib

from ..version import MANIM_CE_VERSION


def content_key(source: str, quality: str, manim_version: str = MANIM_CE_VERSION) -> str:
    """Stable hex digest for ``(source, quality, manim_version)``.

    Components are length-prefixed before hashing so that no rearrangement of boundaries
    (e.g. a quality string that ends in the source's first char) can collide with a
    different triple.
    """

    h = hashlib.sha256()
    for part in (manim_version, quality, source):
        encoded = part.encode("utf-8")
        h.update(str(len(encoded)).encode("ascii"))
        h.update(b"\x00")
        h.update(encoded)
    return h.hexdigest()
