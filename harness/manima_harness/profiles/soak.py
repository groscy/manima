"""Soak profile (task 2.2): one prompt at a time, sustained.

Sequential and slow on purpose. Nothing here stresses concurrency; it stresses
*duration* — memory stability, KV-cache growth, and thermals over hours (proposal.md).
The background Apertus sampler is what actually captures the soak signal (VRAM
high-water creeping up, tok/s sagging as the machine heats), so a soak run is only as
informative as the side channel wired into ``ApertusMetrics``.
"""

from __future__ import annotations

import time

from ..client import ManimaClient
from ..record import RunRecord
from . import Profile


class SoakProfile(Profile):
    name = "soak"

    def __init__(
        self,
        *args,
        duration_s: float | None = None,
        max_iterations: int | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        # Sustain for a wall-clock duration, or for a fixed number of prompts. If both
        # are None, make exactly one pass over the suite — a smoke soak.
        self.duration_s = duration_s
        self.max_iterations = max_iterations

    async def run(self, client: ManimaClient) -> list[RunRecord]:
        prompts = list(self.suite)
        if not prompts:
            return []

        runs: list[RunRecord] = []
        deadline = None if self.duration_s is None else time.monotonic() + self.duration_s
        cap = self.max_iterations
        if cap is None and self.duration_s is None:
            cap = len(prompts)

        async with self._sampling():
            i = 0
            while True:
                if cap is not None and i >= cap:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break
                prompt = prompts[i % len(prompts)]
                runs.append(await self._generate_job(client, prompt))
                i += 1

        self._drain_calls(client)
        return runs
