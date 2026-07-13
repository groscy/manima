"""Success rates, attempt distribution, and convergence (tasks 5.1-5.3)."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..record import RunRecord


@dataclass
class SuccessRates:
    """First-pass and post-repair success, sliced by (condition, tier) — task 5.1."""

    condition: str
    tier: str
    n: int
    first_pass: float
    post_repair: float

    @property
    def repair_lift(self) -> float:
        """How much repair added beyond first pass. Zero ⇒ repair changed nothing."""

        return self.post_repair - self.first_pass


def success_rates(runs: list[RunRecord]) -> list[SuccessRates]:
    """One row per (condition, tier). first-pass = succeeded on attempt 1;
    post-repair = succeeded at all (specs/generate distinguishes the two)."""

    grouped: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    for r in runs:
        grouped[(r.condition, r.tier)].append(r)

    rows: list[SuccessRates] = []
    for (condition, tier), group in sorted(grouped.items()):
        n = len(group)
        first = sum(1 for r in group if r.first_pass_success) / n
        post = sum(1 for r in group if r.succeeded) / n
        rows.append(
            SuccessRates(
                condition=condition,
                tier=tier,
                n=n,
                first_pass=first,
                post_repair=post,
            )
        )
    return rows


def attempt_distribution(runs: list[RunRecord]) -> dict[str, dict[int, int]]:
    """Histogram of attempt counts per condition — task 5.2.

    A repair loop that rarely gets past attempt 1 looks very different from one that
    routinely burns the whole budget; this shows which.
    """

    dist: dict[str, Counter] = defaultdict(Counter)
    for r in runs:
        dist[r.condition][r.attempt_count] += 1
    return {cond: dict(sorted(counter.items())) for cond, counter in dist.items()}


@dataclass
class ConvergenceReport:
    """Attempt-over-attempt behaviour of the repair loop — task 5.3.

    ``marginal_success[k]`` is P(succeed exactly at attempt k | reached attempt k).
    Rising with k ⇒ repair is *converging* (each pass uses the traceback to get
    closer). Flat ⇒ it is merely *resampling*, and per task 6.3 / specs/generate the
    budget is buying nothing and should be cut, not raised.
    """

    condition: str
    marginal_success: dict[int, float] = field(default_factory=dict)
    reached: dict[int, int] = field(default_factory=dict)
    repair_yield: float | None = None  # of first-pass failures, fraction later fixed

    @property
    def converges(self) -> bool | None:
        """True if later attempts succeed at a higher conditional rate than the first.

        A coarse verdict — the report carries the full curve for a human to judge — but
        enough to flag a resampling loop automatically.
        """

        ks = sorted(self.marginal_success)
        if len(ks) < 2:
            return None
        return self.marginal_success[ks[-1]] > self.marginal_success[ks[0]]


def convergence(runs: list[RunRecord]) -> list[ConvergenceReport]:
    reports: list[ConvergenceReport] = []
    by_condition: dict[str, list[RunRecord]] = defaultdict(list)
    for r in runs:
        by_condition[r.condition].append(r)

    for condition, group in sorted(by_condition.items()):
        reached: Counter = Counter()
        succeeded_at: Counter = Counter()
        max_attempts = max((r.attempt_count for r in group), default=0)

        for r in group:
            for k in range(1, r.attempt_count + 1):
                reached[k] += 1
            if r.succeeded and r.attempt_count >= 1:
                succeeded_at[r.attempt_count] += 1

        marginal = {
            k: (succeeded_at[k] / reached[k]) if reached[k] else 0.0
            for k in range(1, max_attempts + 1)
        }

        first_pass_failures = [r for r in group if not r.first_pass_success]
        repair_yield = None
        if first_pass_failures:
            fixed = sum(1 for r in first_pass_failures if r.succeeded)
            repair_yield = fixed / len(first_pass_failures)

        reports.append(
            ConvergenceReport(
                condition=condition,
                marginal_success=marginal,
                reached=dict(reached),
                repair_yield=repair_yield,
            )
        )
    return reports
