"""Throughput degradation vs concurrency (5.5) and VRAM headroom (5.6).

Both draw on the Apertus side channel, so both are only as real as the probe wired into
a run. When the side channel was absent (``NullApertusProbe``), the inputs are ``None``
and these functions say so rather than inventing a number — an unobservable metric is a
finding, not a zero (proposal.md, Scope/Out).
"""

from __future__ import annotations

from dataclasses import dataclass

# project.md: 16 GB VRAM host. The whole "why 8B" argument is arithmetic against this.
DEFAULT_TOTAL_VRAM_MB = 16 * 1024


@dataclass
class ThroughputPoint:
    concurrency: int
    mean_tok_per_s: float | None
    total_latency_p95_s: float | None
    success_rate: float | None
    # tok/s as a fraction of the lowest-concurrency baseline. 1.0 = no degradation;
    # < 1.0 = the model slows under concurrent pressure. None if unmeasured.
    degradation_vs_baseline: float | None = None


def throughput_curve(points: list[dict]) -> list[ThroughputPoint]:
    """Build the degradation curve from per-concurrency run summaries.

    Each input dict: ``concurrency`` (int), ``mean_tok_per_s`` (float|None),
    ``total_latency_p95_s`` (float|None), ``success_rate`` (float|None) — typically one
    per burst run in a concurrency sweep. The baseline is the lowest concurrency that
    actually produced a tok/s reading.
    """

    built = [
        ThroughputPoint(
            concurrency=int(p["concurrency"]),
            mean_tok_per_s=p.get("mean_tok_per_s"),
            total_latency_p95_s=p.get("total_latency_p95_s"),
            success_rate=p.get("success_rate"),
        )
        for p in points
    ]
    built.sort(key=lambda pt: pt.concurrency)

    baseline = next((pt.mean_tok_per_s for pt in built if pt.mean_tok_per_s), None)
    if baseline:
        for pt in built:
            if pt.mean_tok_per_s is not None:
                pt.degradation_vs_baseline = pt.mean_tok_per_s / baseline
    return built


@dataclass
class VramHeadroom:
    observable: bool
    high_water_mb: float | None
    total_mb: float
    headroom_mb: float | None
    headroom_frac: float | None

    @property
    def fits(self) -> bool | None:
        """Whether the run stayed within the VRAM budget. None if unobserved."""

        if self.headroom_mb is None:
            return None
        return self.headroom_mb > 0


def vram_headroom(
    high_water_mb: float | None,
    total_mb: float = DEFAULT_TOTAL_VRAM_MB,
) -> VramHeadroom:
    """Headroom left under the longest grounded prompts (task 5.6).

    Grounding injection makes the prompt longest exactly when the KV cache is largest,
    so the tightest headroom shows up on the hard tier with a full grounding payload —
    run a soak against the longest-expected prompt to isolate it. This computes headroom
    from an observed high-water mark; with no side channel it reports unobservable.
    """

    if high_water_mb is None:
        return VramHeadroom(
            observable=False,
            high_water_mb=None,
            total_mb=total_mb,
            headroom_mb=None,
            headroom_frac=None,
        )
    headroom = total_mb - high_water_mb
    return VramHeadroom(
        observable=True,
        high_water_mb=high_water_mb,
        total_mb=total_mb,
        headroom_mb=headroom,
        headroom_frac=headroom / total_mb if total_mb else None,
    )
