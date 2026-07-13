"""Hosted-model escalation generator (task 9.1, ADR-003, specs/generate).

`AnimationGenerator` adapter for the deny-by-default escalation path. The job manager only
ever constructs the request after the escalation triple gate has opened (task 9.2); this
adapter is just the wire to the hosted model.

Two sovereignty guarantees are structural, not documentation:
  - the API key is read from the environment by the SDK — it is **never** a constructor or
    tool argument, so it cannot arrive via a call (task 9.1); and
  - the ``anthropic`` import is lazy and lives in its own optional extra, so a sovereign
    deployment that never escalates installs no hosted-model SDK at all.
"""

from __future__ import annotations

import os
import re

from ..version import MANIM_CE_VERSION

_CODE_BLOCK = re.compile(r"```(?:python)?[ \t]*\r?\n(.*?)(?:\r?\n```|\Z)", re.DOTALL)

_SYSTEM = """\
You write a single self-contained Manim Community Edition scene, targeting version {version}.
Manim CE only (never ManimGL). Exactly one Scene/ThreeDScene subclass, all animation in
construct(self), import from `manim` only, runs offline. Output ONLY the Python source.
"""


class AnthropicEscalationGenerator:
    """`AnimationGenerator` adapter over the Anthropic Messages API."""

    def __init__(
        self,
        model: str,
        *,
        manim_version: str = MANIM_CE_VERSION,
        max_tokens: int = 4096,
    ) -> None:
        self._model = model
        self._manim_version = manim_version
        self._max_tokens = max_tokens
        self._client = None

    @property
    def identity(self) -> str:
        return f"escalation:{self._model}"

    def _connect(self):
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:  # pragma: no cover - env dependent
                raise RuntimeError(
                    "escalation needs the 'escalation' extra: "
                    "pip install manima-server[escalation]"
                ) from exc
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set; escalation cannot run. The key is read "
                    "from the environment only, never passed as an argument."
                )
            self._client = AsyncAnthropic()
        return self._client

    async def generate(
        self,
        prompt: str,
        *,
        grounding: list[str],
        repair_source: str | None = None,
        repair_traceback: str | None = None,
    ) -> str:
        client = self._connect()
        user = _build_user_message(prompt, grounding, repair_source, repair_traceback)
        message = await client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SYSTEM.format(version=self._manim_version),
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            b.text for b in message.content if getattr(b, "type", None) == "text"
        )
        return _strip_fences(text)


def _build_user_message(prompt, grounding, repair_source, repair_traceback) -> str:
    parts = []
    if grounding:
        parts.append("Relevant Manim CE API:\n" + "\n---\n".join(grounding))
    parts.append(f"Task: {prompt}")
    if repair_source is not None and repair_traceback is not None:
        parts.append(
            "The local model could not produce runnable source. Its last attempt and error:\n"
            f"Source:\n{repair_source}\n\nTraceback:\n{repair_traceback}"
        )
    return "\n\n".join(parts)


def _strip_fences(text: str) -> str:
    """Extract the first fenced code block, tolerating prose around it and an unclosed
    fence (a model routinely explains its answer despite being told to output only code)."""

    text = text.strip()
    match = _CODE_BLOCK.search(text)
    if match:
        return match.group(1).strip()
    return text
