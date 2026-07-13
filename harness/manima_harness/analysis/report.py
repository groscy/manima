"""Assemble the analysis report (section 5) and surface the section-6 advisories.

Reads one or more run directories from disk, runs every section-5 analysis, and emits a
Markdown report. It also renders the "act on what you find" branches (section 6) as
*advisories* — it computes which branch the evidence points to (corpus is the lever /
grounding won't help / cut the repair budget / fix MANIMA) but never acts. Acting is a
human decision, and several branches depend on the hand-classified taxonomy, which the
report is honest about when it is still unlabelled.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..prompts import PromptSuite
from ..record import RunRecord, load_attempts, load_runs
from .success import attempt_distribution, convergence, success_rates
from .taxonomy import FailureClass, taxonomy_report
from .throughput import throughput_curve, vram_headroom


@dataclass
class LoadedRun:
    path: Path
    runs: list[RunRecord]
    attempts: list
    metrics: dict = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)


def load_run_dir(path: Path) -> LoadedRun:
    path = Path(path)
    return LoadedRun(
        path=path,
        runs=load_runs(path),
        attempts=load_attempts(path),
        metrics=_read_json(path / "metrics.json"),
        manifest=_read_json(path / "run.json"),
    )


def build_report(run_dirs: list[Path], suite: PromptSuite | None = None) -> str:
    loaded = [load_run_dir(p) for p in run_dirs]
    all_runs = [r for lr in loaded for r in lr.runs]
    all_attempts = [a for lr in loaded for a in lr.attempts]

    lines: list[str] = ["# Apertus load-test — analysis report", ""]
    lines += _section_success(all_runs)
    lines += _section_attempts(all_runs)
    lines += _section_convergence(all_runs)
    lines += _section_taxonomy(all_attempts, all_runs, suite)
    lines += _section_throughput(loaded)
    lines += _section_vram(loaded)
    lines += _section_advisories(all_runs, all_attempts, loaded)
    return "\n".join(lines) + "\n"


# -- sections -------------------------------------------------------------------


def _section_success(runs: list[RunRecord]) -> list[str]:
    out = ["## 5.1 Success rates (first-pass / post-repair)", ""]
    rows = success_rates(runs)
    if not rows:
        return out + ["_No runs recorded._", ""]
    out += ["| condition | tier | n | first-pass | post-repair | repair lift |",
            "|---|---|---|---|---|---|"]
    for r in rows:
        out.append(
            f"| {r.condition} | {r.tier} | {r.n} | {r.first_pass:.0%} | "
            f"{r.post_repair:.0%} | {r.repair_lift:+.0%} |"
        )
    return out + [""]


def _section_attempts(runs: list[RunRecord]) -> list[str]:
    out = ["## 5.2 Attempt distribution", ""]
    dist = attempt_distribution(runs)
    if not dist:
        return out + ["_No runs recorded._", ""]
    for condition, hist in dist.items():
        pretty = ", ".join(f"{k}×{v}" for k, v in hist.items())
        out.append(f"- **{condition}**: {pretty}  _(attempts × jobs)_")
    return out + [""]


def _section_convergence(runs: list[RunRecord]) -> list[str]:
    out = ["## 5.3 Repair convergence (attempt-over-attempt)", ""]
    reports = convergence(runs)
    if not reports:
        return out + ["_No runs recorded._", ""]
    for rep in reports:
        verdict = (
            "converges" if rep.converges
            else "resampling (no improvement)" if rep.converges is False
            else "insufficient data"
        )
        curve = ", ".join(f"a{k}:{v:.0%}" for k, v in rep.marginal_success.items())
        yield_str = "n/a" if rep.repair_yield is None else f"{rep.repair_yield:.0%}"
        out.append(f"- **{rep.condition}** — {verdict}; repair yield {yield_str}")
        if curve:
            out.append(f"  - marginal success by attempt: {curve}")
    return out + [""]


def _section_taxonomy(attempts: list, runs: list[RunRecord], suite: PromptSuite | None) -> list[str]:
    out = ["## 5.4 Failure taxonomy (hand-classified)", ""]
    report = taxonomy_report(attempts, runs, suite)
    out.append(
        f"- failed attempts: {report.total_failed_attempts} "
        f"({report.hand_labelled} hand-labelled, {report.unclassified} unclassified)"
    )
    if report.total_failed_attempts:
        for klass, count in sorted(report.counts.items()):
            if count:
                out.append(f"  - {klass}: {count}")
    if report.unclassified:
        out.append(
            f"- ⚠ {report.unclassified} failed attempts are not yet hand-classified. "
            "Run the taxonomy pass over `attempts.jsonl` + `tracebacks/` before trusting "
            "the taxonomy-dependent advisories below."
        )
    out.append(
        f"- {report.needs_semantic_review} successful runs still need a semantic check "
        "against each prompt's `expected` list — that is where SEMANTIC failures hide "
        "(the probe cannot see them)."
    )
    return out + [""]


def _section_throughput(loaded: list[LoadedRun]) -> list[str]:
    out = ["## 5.5 Throughput degradation vs concurrency", ""]
    points = []
    for lr in loaded:
        concurrency = lr.manifest.get("concurrency")
        if concurrency is None:
            continue
        apertus = lr.metrics.get("apertus", {})
        manima = lr.metrics.get("manima", {})
        points.append(
            {
                "concurrency": concurrency,
                "mean_tok_per_s": apertus.get("mean_generation_tok_per_s"),
                "total_latency_p95_s": _overall_p95(manima),
                "success_rate": _success_rate(lr.runs),
            }
        )
    if not points:
        return out + [
            "_No concurrency-labelled runs. Run the burst profile across a sweep of "
            "concurrency levels to build this curve._",
            "",
        ]
    out += ["| concurrency | tok/s | p95 tool latency | success | vs baseline |",
            "|---|---|---|---|---|"]
    for pt in throughput_curve(points):
        out.append(
            f"| {pt.concurrency} | {_fmt(pt.mean_tok_per_s)} | "
            f"{_fmt(pt.total_latency_p95_s, 's')} | {_fmt_pct(pt.success_rate)} | "
            f"{_fmt_pct(pt.degradation_vs_baseline)} |"
        )
    return out + [""]


def _section_vram(loaded: list[LoadedRun]) -> list[str]:
    out = ["## 5.6 VRAM headroom under the longest grounded prompts", ""]
    high_waters = [
        lr.metrics.get("apertus", {}).get("vram_high_water_mb")
        for lr in loaded
    ]
    observed = [v for v in high_waters if v is not None]
    if not observed:
        return out + [
            "_VRAM was not observed — no Apertus side channel was wired up. This is a "
            "finding about the MCP surface, not a zero: wire an `nvidia-smi` probe to "
            "collect it._",
            "",
        ]
    hr = vram_headroom(max(observed))
    out.append(
        f"- high-water: {hr.high_water_mb:.0f} MB of {hr.total_mb:.0f} MB "
        f"→ headroom {hr.headroom_mb:.0f} MB ({hr.headroom_frac:.0%}); "
        f"{'fits' if hr.fits else 'OVER BUDGET'}"
    )
    return out + [""]


def _section_advisories(runs: list[RunRecord], attempts: list, loaded: list[LoadedRun]) -> list[str]:
    """Section 6 — which branch the evidence points to. Advisory only; never acts."""

    out = ["## 6. Act on what you find (advisory)", ""]
    tax = taxonomy_report(attempts, runs)

    # 6.4 — did MANIMA itself buckle? Observable directly from the surface.
    violations = sum(
        len(lr.metrics.get("manima", {}).get("latency_contract_violations", []))
        for lr in loaded
    )
    if violations:
        out.append(
            f"- **6.4 Fix MANIMA.** {violations} tool call(s) breached the 2 s contract. "
            "The async contract is broken — a real bug the harness earned its keep by "
            "finding, not a tuning knob."
        )

    # 6.3 — convergence. Purely from run records, no hand-labelling needed.
    for rep in convergence(runs):
        if rep.converges is False:
            out.append(
                f"- **6.3 Cut the repair budget ({rep.condition}).** No "
                "attempt-over-attempt improvement — the budget buys nothing. Cut it to "
                "1; do not raise it hoping for a different result."
            )

    # 6.1 / 6.2 — depend on the hand-classified taxonomy.
    if not tax.fully_classified:
        out.append(
            "- **6.1 / 6.2 pending.** The corpus-vs-ceiling call needs the taxonomy "
            "hand-classified first; it is not yet complete."
        )
    else:
        manimgl = tax.counts.get(FailureClass.MANIMGL_CONFUSION.value, 0)
        semantic = tax.counts.get(FailureClass.SEMANTIC.value, 0)
        dominant = max(tax.counts.items(), key=lambda kv: kv[1], default=(None, 0))
        if dominant[0] == FailureClass.MANIMGL_CONFUSION.value and manimgl:
            out.append(
                "- **6.1 Improve the corpus.** Failures are dominated by "
                "ManimGL-confusion — the grounding corpus is the lever. Cheap, and "
                "likely to move the number. Improve it and re-run."
            )
        if dominant[0] == FailureClass.SEMANTIC.value and semantic:
            out.append(
                "- **6.2 Record the ceiling.** Failures are dominated by semantic "
                "errors — the model does not understand the maths. Grounding will not "
                "help; record the ceiling honestly rather than tuning around it."
            )

    if len(out) == 2:
        out.append("- _No advisory triggered yet — need more runs or a completed taxonomy pass._")
    return out + [""]


# -- helpers --------------------------------------------------------------------


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _overall_p95(manima_metrics: dict) -> float | None:
    by_tool = manima_metrics.get("latency_by_tool", {})
    p95s = [stats.get("p95") for stats in by_tool.values() if stats.get("p95") is not None]
    return max(p95s) if p95s else None


def _success_rate(runs: list[RunRecord]) -> float | None:
    if not runs:
        return None
    return sum(1 for r in runs if r.succeeded) / len(runs)


def _fmt(value: float | None, unit: str = "") -> str:
    return "—" if value is None else f"{value:.1f}{unit}"


def _fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"
