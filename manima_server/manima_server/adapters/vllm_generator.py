"""Apertus-via-vLLM generator (task 7.2, specs/generate).

`AnimationGenerator` adapter talking to the local vLLM OpenAI-compatible endpoint. It
assembles the grounded prompt — pinned-CE grounding snippets plus, on a repair pass, the
previous source and its traceback — and returns Manim CE source.

It sits behind the port, so swapping the local model for another requires no change to the
core, the repair loop, or the tool surface (task 7.3, specs/generate). The ``openai`` client
is imported lazily; a render-only deployment never touches it.
"""

from __future__ import annotations

import re

from ..version import MANIM_CE_VERSION

_FENCE = re.compile(r"^```(?:python)?\s*\n(.*?)\n```\s*$", re.DOTALL)

_SYSTEM = """\
You write a single self-contained Manim Community Edition scene, targeting version {version}.
Rules:
- Manim CE only. Never ManimGL: no ShowCreation (use Create), no get_graph (use axes.plot),
  no TexMobject (use MathTex/Tex), no continual-animation updaters.
- Exactly one Scene (or ThreeDScene) subclass; all animation inside construct(self).
- Import from `manim` only. It runs offline in a sandbox with no network.
- Output ONLY the Python source — no prose, no markdown fences.
"""


class ApertusVLLMGenerator:
    """`AnimationGenerator` adapter over a vLLM OpenAI-compatible endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        manim_version: str = MANIM_CE_VERSION,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._manim_version = manim_version
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client = None

    @property
    def identity(self) -> str:
        return f"apertus:{self._model}"

    def _connect(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:  # pragma: no cover - env dependent
                raise RuntimeError(
                    "the local generator needs the 'generate' extra: "
                    "pip install manima-server[generate]"
                ) from exc
            # vLLM ignores the key but the client requires one.
            self._client = AsyncOpenAI(base_url=self._base_url, api_key="EMPTY")
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
        resp = await client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[
                {"role": "system", "content": _SYSTEM.format(version=self._manim_version)},
                {"role": "user", "content": user},
            ],
        )
        return _strip_fences(resp.choices[0].message.content or "")


def _build_user_message(
    prompt: str,
    grounding: list[str],
    repair_source: str | None,
    repair_traceback: str | None,
) -> str:
    parts = []
    if grounding:
        parts.append("Relevant Manim CE API for the pinned version:\n" + "\n---\n".join(grounding))
    parts.append(f"Task: {prompt}")
    if repair_source is not None and repair_traceback is not None:
        # Repair context: the failing source and the exact traceback, so the next attempt
        # can fix the named construct rather than resample blindly (specs/generate).
        parts.append(
            "Your previous attempt failed. Fix it.\n"
            f"Previous source:\n{repair_source}\n\n"
            f"Traceback:\n{repair_traceback}"
        )
    return "\n\n".join(parts)


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = _FENCE.match(text)
    return m.group(1).strip() if m else text
