"""Repair-heavy profile (task 2.4): prompts chosen to reliably fail first pass.

Selects the high-``manimgl_risk`` prompts — the ones whose natural CE solution sits on
API that drifted from ManimGL, where an 8B model most often emits code that does not
run. That drives the repair loop toward its worst case: several dependent, sequential
generations per animation (proposal.md, "The load profile has natural shape").

Sequential, not concurrent — the subject under test is the *repair loop*, and the
per-attempt trace it produces, not queue pressure. Every attempt's source and traceback
is persisted (task 2.6), which is exactly the raw material the attempt-over-attempt
convergence analysis (task 5.3) and the failure taxonomy (task 5.4) read.
"""

from __future__ import annotations

from ..client import ManimaClient
from ..record import RunRecord
from . import Profile


class RepairHeavyProfile(Profile):
    name = "repair-heavy"

    def __init__(self, *args, repeats: int = 1, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.repeats = repeats

    async def run(self, client: ManimaClient) -> list[RunRecord]:
        prompts = self.suite.high_manimgl_risk()
        if not prompts:
            # Not silently empty: if the suite carries no high-risk prompts, the
            # repair loop can't be stressed and that must be visible, not a no-op.
            raise ValueError(
                "no high manimgl_risk prompts in the suite; repair-heavy has nothing "
                "to push the repair loop with"
            )

        runs: list[RunRecord] = []
        async with self._sampling():
            for _ in range(self.repeats):
                for prompt in prompts:
                    runs.append(await self._generate_job(client, prompt))

        self._drain_calls(client)
        return runs
