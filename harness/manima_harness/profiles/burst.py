"""Burst profile (task 2.3): N concurrent generate calls, N sweepable.

One run fires ``concurrency`` ``generate_animation`` calls at once and waits for all to
finish; ``waves`` repeats that burst. Sweeping N is done by running the profile at
several concurrency levels — that sweep is what feeds the throughput-degradation curve
(task 5.5) and the per-level 2-second contract check (task 4.3). The pressure lands on
vLLM's queue, the job manager, and container churn, all at once.
"""

from __future__ import annotations

import anyio

from ..client import ManimaClient
from ..record import RunRecord
from . import Profile


class BurstProfile(Profile):
    name = "burst"

    def __init__(self, *args, concurrency: int = 4, waves: int = 1, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if concurrency < 1:
            raise ValueError("burst concurrency must be >= 1")
        self.concurrency = concurrency
        self.waves = waves

    async def run(self, client: ManimaClient) -> list[RunRecord]:
        prompts = list(self.suite)
        if not prompts:
            return []

        runs: list[RunRecord] = []
        # Round-robin the suite across the whole burst so a wave of N is N distinct
        # prompts where possible, not the same prompt N times (which the cache would
        # collapse — a different, deliberate test left to the mixed/cache work).
        cursor = 0
        async with self._sampling():
            for _ in range(self.waves):
                wave = [prompts[(cursor + k) % len(prompts)] for k in range(self.concurrency)]
                cursor += self.concurrency
                results: list[RunRecord] = []

                async with anyio.create_task_group() as tg:

                    async def one(p=None) -> None:
                        results.append(await self._generate_job(client, p))

                    for prompt in wave:
                        tg.start_soon(one, prompt)

                runs.extend(results)

        self._drain_calls(client)
        return runs
