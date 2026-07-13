"""Mixed profile (task 2.5): interleave render_animation and generate_animation.

Runs both tool surfaces at once to expose contention between the thin and thick paths
— shared sandbox, shared job manager, shared container budget. The generate side draws
from the prompt suite; the render side submits a fixed known-good scene, because the
render path here is a *load source*, not a correctness test — it should render reliably
so any failure points at contention rather than at bad source.

Both paths run concurrently under a capacity limiter so the interleave is genuine
pressure, not lock-step alternation. render jobs are recorded under a distinct
condition so section-5 analysis can tell the two paths apart.
"""

from __future__ import annotations

import anyio

from ..client import ManimaClient
from ..record import RunRecord
from . import Profile

COND_RENDER = "render-known-good"

# Minimal scene valid on any Manim CE version — the render side's payload. Kept
# deliberately trivial so it is not itself a source of failures.
KNOWN_GOOD_SOURCE = """\
from manim import *


class HarnessProbe(Scene):
    def construct(self):
        self.play(Create(Circle()))
"""


class MixedProfile(Profile):
    name = "mixed"

    def __init__(
        self,
        *args,
        concurrency: int = 4,
        rounds: int = 1,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.concurrency = concurrency
        self.rounds = rounds

    async def run(self, client: ManimaClient) -> list[RunRecord]:
        prompts = list(self.suite)
        if not prompts:
            return []

        runs: list[RunRecord] = []
        limiter = anyio.CapacityLimiter(self.concurrency)
        cursor = 0

        async with self._sampling():
            for _ in range(self.rounds):
                # Interleave: alternate generate / render across the round.
                plan: list[tuple[str, object]] = []
                for prompt in prompts:
                    plan.append(("generate", prompt))
                    plan.append(("render", prompt))

                results: list[RunRecord] = []

                async def one(kind: str, prompt) -> None:
                    async with limiter:
                        if kind == "generate":
                            results.append(await self._generate_job(client, prompt))
                        else:
                            results.append(
                                await self._render_job(
                                    client, prompt, KNOWN_GOOD_SOURCE, COND_RENDER
                                )
                            )

                async with anyio.create_task_group() as tg:
                    for kind, prompt in plan:
                        tg.start_soon(one, kind, prompt)

                runs.extend(results)
                cursor += 1

        self._drain_calls(client)
        return runs
