"""Analysis over persisted runs (section 5).

Every function here reads the durable records written during a run — ``runs.jsonl`` and
``attempts.jsonl`` — never live counters. That is deliberate: the taxonomy and the
convergence question depend on re-reading raw source and tracebacks (task 2.6), so the
analysis is reproducible from disk long after the load run is over, and re-runnable as
hand-classification labels are filled in.
"""

from __future__ import annotations

from .success import (
    ConvergenceReport,
    SuccessRates,
    attempt_distribution,
    convergence,
    success_rates,
)
from .taxonomy import FailureClass, TaxonomyReport, pre_classify, taxonomy_report
from .throughput import ThroughputPoint, throughput_curve, vram_headroom

__all__ = [
    "SuccessRates",
    "success_rates",
    "attempt_distribution",
    "ConvergenceReport",
    "convergence",
    "FailureClass",
    "pre_classify",
    "TaxonomyReport",
    "taxonomy_report",
    "ThroughputPoint",
    "throughput_curve",
    "vram_headroom",
]
