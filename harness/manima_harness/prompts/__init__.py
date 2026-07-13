"""The graded prompt suite (section 1).

Prompts are authored as YAML data (``easy.yaml`` / ``medium.yaml`` / ``hard.yaml``)
so the suite is content, not code, and can be extended without touching the harness.
Each prompt carries, per task 1.4, an ``expected`` list — what a *correct* scene must
contain. The probe render (specs/generate) is a syntax/API oracle only; it cannot see
that a scene is animating the wrong thing. Semantic-failure classification (task 5.4)
is done by a human reading the rendered artifact against this list, so the list has to
exist up front.

``manimgl_risk`` flags prompts whose natural CE solution sits on API that drifted from
ManimGL (creation animations, graphing, 3D camera, updaters). The repair-heavy profile
(task 2.4) selects the high-risk ones to push the repair loop toward its worst case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from importlib import resources
from typing import Iterable

import yaml


class Tier(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class ManimglRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class Prompt:
    id: str
    tier: Tier
    prompt: str
    expected: tuple[str, ...]
    manimgl_risk: ManimglRisk
    notes: str | None = None


@dataclass(frozen=True)
class PromptSuite:
    prompts: tuple[Prompt, ...] = field(default_factory=tuple)

    def __iter__(self):
        return iter(self.prompts)

    def __len__(self) -> int:
        return len(self.prompts)

    def by_tier(self, tier: Tier) -> list[Prompt]:
        return [p for p in self.prompts if p.tier is tier]

    def high_manimgl_risk(self) -> list[Prompt]:
        """Prompts most likely to fail first pass — the repair-heavy selection."""

        return [p for p in self.prompts if p.manimgl_risk is ManimglRisk.HIGH]

    def get(self, prompt_id: str) -> Prompt:
        for p in self.prompts:
            if p.id == prompt_id:
                return p
        raise KeyError(prompt_id)


_TIER_FILES = {Tier.EASY: "easy.yaml", Tier.MEDIUM: "medium.yaml", Tier.HARD: "hard.yaml"}


def load_suite(tiers: Iterable[Tier] | None = None) -> PromptSuite:
    """Load and validate the prompt suite from the packaged YAML files."""

    wanted = list(tiers) if tiers is not None else list(Tier)
    prompts: list[Prompt] = []
    for tier in wanted:
        raw = yaml.safe_load(
            resources.files(__package__).joinpath(_TIER_FILES[tier]).read_text("utf-8")
        )
        for entry in raw:
            prompts.append(
                Prompt(
                    id=entry["id"],
                    tier=tier,
                    prompt=entry["prompt"].strip(),
                    expected=tuple(entry["expected"]),
                    manimgl_risk=ManimglRisk(entry.get("manimgl_risk", "low")),
                    notes=entry.get("notes"),
                )
            )
    _validate(prompts)
    return PromptSuite(prompts=tuple(prompts))


def _validate(prompts: list[Prompt]) -> None:
    ids = [p.id for p in prompts]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate prompt ids: {sorted(dupes)}")
    for p in prompts:
        if not p.expected:
            # Task 1.4 is not optional: a prompt with no correctness spec cannot be
            # classified for semantic failure, so refuse to load it silently.
            raise ValueError(f"prompt {p.id} has no 'expected' correctness requirements")
