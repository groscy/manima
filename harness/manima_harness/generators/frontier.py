"""Frontier-model source generator — the control condition (task 3.1).

Concrete ``SourceGenerator`` backed by the Anthropic Messages API. It generates Manim
CE source that the harness then submits through ``render_animation`` (task 3.2), so the
frontier model faces the exact same sandbox, probe, and oracle as Apertus.

Deliberately kept out of the harness core's import graph: ``anthropic`` is an optional
extra (``pip install manima-harness[frontier]``) and the API key is read from the
environment by the SDK, never taken as an argument. A sovereign Apertus-only run never
touches this module.

Parity note (proposal.md, "The control condition"): the value of the control is that
it isolates *model capability* from prompt/corpus quality. The instruction below pins
the target to the same Manim CE version as the render image and forbids ManimGL — the
same drift the grounding corpus fights for Apertus — so a frontier failure points at
the prompt template rather than at raw capability. Keep this template in sync with
MANIMA's own generation prompt when comparing the two conditions directly.
"""

from __future__ import annotations

import os
import re

from . import GeneratedSource

# A current frontier Claude model. Overridable so the control can be re-run against a
# different frontier as they evolve, without touching the harness.
DEFAULT_MODEL = "claude-opus-4-8"

_SYSTEM_TEMPLATE = """\
You are generating a single, self-contained Manim Community Edition scene.

Hard requirements:
- Target Manim CE version {manim_version} exactly. Do NOT use ManimGL (3b1b/manim)
  constructs: no ShowCreation (use Create), no get_graph (use axes.plot), no
  TexMobject (use MathTex/Tex), no continual-animation updaters.
- Define exactly one Scene (or ThreeDScene) subclass. Put all animation in
  construct(self).
- Import from `manim` only. The scene runs offline in a sandbox with no network.
- Output ONLY the Python source. No prose, no explanation, no markdown fences.
"""

_FENCE = re.compile(r"^```(?:python)?\s*\n(.*?)\n```\s*$", re.DOTALL)


class AnthropicFrontierGenerator:
    """SourceGenerator adapter over the Anthropic Messages API."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        manim_version: str = "unpinned",
        max_tokens: int = 4096,
    ) -> None:
        # Import lazily so importing the package (or running an Apertus-only profile)
        # does not require the anthropic SDK to be installed.
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "the frontier control needs the 'anthropic' extra: "
                "pip install manima-harness[frontier]"
            ) from exc
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set; the frontier control cannot run. "
                "The harness never accepts the key as an argument — set it in the env."
            )
        self._client = AsyncAnthropic()
        self._model = model
        self._manim_version = manim_version
        self._max_tokens = max_tokens

    @property
    def identity(self) -> str:
        return f"frontier:{self._model}"

    async def generate(self, prompt: str) -> GeneratedSource:
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SYSTEM_TEMPLATE.format(manim_version=self._manim_version),
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
        return GeneratedSource(
            source=_strip_fences(text),
            model=self._model,
            input_tokens=getattr(message.usage, "input_tokens", None),
            output_tokens=getattr(message.usage, "output_tokens", None),
        )


def _strip_fences(text: str) -> str:
    text = text.strip()
    match = _FENCE.match(text)
    return match.group(1).strip() if match else text
