"""Source generators for the control condition (section 3).

The control condition answers "is an Apertus number even interpretable?" (proposal.md).
It generates Manim source with a *frontier* model and submits it through the same
``render_animation`` path — same sandbox, same probe, same mechanical oracle. If the
frontier model also scores poorly, the corpus or prompt template is the problem, not
Apertus.

The generator sits behind a small port so the control model is swappable, mirroring
MANIMA's own ``AnimationGenerator`` port (specs/generate). The harness core imports
only this Protocol; the concrete Anthropic adapter lives in ``frontier`` and is loaded
lazily so a sovereign Apertus-only run pulls in no hosted-model dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class GeneratedSource:
    """Raw model output, unpacked into submittable source plus accounting."""

    source: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@runtime_checkable
class SourceGenerator(Protocol):
    """Turn a natural-language prompt into Manim CE source."""

    @property
    def identity(self) -> str:
        """Stable label recorded as the run ``condition`` (e.g. the model id)."""
        ...

    async def generate(self, prompt: str) -> GeneratedSource: ...
