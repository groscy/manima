"""Durable record of every attempt.

Task 2.6 is emphatic: persist raw source and raw traceback for *every* attempt,
because "the taxonomy depends on reading these, not on aggregate counters". So the
unit of persistence is the attempt, not the job, and raw text is written verbatim to
its own file — never truncated, never summarised into a counter.

Layout under ``<out_dir>/<run_id>/``::

    run.json                      run-level manifest (profile, config, timing)
    attempts.jsonl                one line per attempt: metadata + pointers
    sources/<job>-<n>.py          raw candidate source, verbatim
    tracebacks/<job>-<n>.txt      raw traceback, verbatim
    metrics.json                  instrument snapshot (written by the profile)

The taxonomy pass (analysis/taxonomy.py) reads ``attempts.jsonl`` and the raw files;
it never trusts a derived count.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .contract import Attempt, JobResult, JobState


@dataclass
class AttemptRecord:
    """One generation/render attempt, flattened for the taxonomy pass."""

    run_id: str
    job_id: str
    prompt_id: str
    tier: str
    condition: str  # "apertus" | "frontier" | server-side generator identity
    attempt_index: int
    generator: str | None
    escalated: bool
    source_path: str | None
    traceback_path: str | None
    # Filled in by hand during the taxonomy pass (task 5.4); starts unset.
    failure_class: str | None = None


@dataclass
class RunRecord:
    """One job's outcome plus timing, for the aggregate analyses (section 5)."""

    run_id: str
    job_id: str
    prompt_id: str
    tier: str
    condition: str
    profile: str
    final_state: str
    succeeded: bool
    attempt_count: int
    first_pass_success: bool
    escalated: bool
    enqueue_latency_s: float | None = None
    total_latency_s: float | None = None
    artifact_uri: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class RecordStore:
    """Append-only sink for attempts and runs under one run directory."""

    def __init__(self, out_dir: Path, run_id: str) -> None:
        self.run_id = run_id
        self.root = Path(out_dir) / run_id
        self.sources = self.root / "sources"
        self.tracebacks = self.root / "tracebacks"
        for d in (self.root, self.sources, self.tracebacks):
            d.mkdir(parents=True, exist_ok=True)
        self._attempts_fp = (self.root / "attempts.jsonl").open("a", encoding="utf-8")
        self._runs_fp = (self.root / "runs.jsonl").open("a", encoding="utf-8")

    # -- writing ----------------------------------------------------------------

    def record_result(
        self,
        *,
        job_id: str,
        prompt_id: str,
        tier: str,
        condition: str,
        profile: str,
        result: JobResult,
        enqueue_latency_s: float | None = None,
        total_latency_s: float | None = None,
    ) -> RunRecord:
        """Persist every attempt of a finished job, plus its run summary.

        This is the whole point of task 2.6: the raw source and traceback of each
        attempt hit disk verbatim before any aggregate is computed.
        """

        attempts = result.attempts or _synthetic_single_attempt(result)
        for attempt in attempts:
            self._write_attempt(job_id, prompt_id, tier, condition, attempt)

        first_pass = result.succeeded and len(attempts) <= 1
        run = RunRecord(
            run_id=self.run_id,
            job_id=job_id,
            prompt_id=prompt_id,
            tier=tier,
            condition=condition,
            profile=profile,
            final_state=result.state.value,
            succeeded=result.succeeded,
            attempt_count=len(attempts),
            first_pass_success=first_pass,
            escalated=any(a.escalated for a in attempts),
            enqueue_latency_s=enqueue_latency_s,
            total_latency_s=total_latency_s,
            artifact_uri=result.artifact_uri,
        )
        self._runs_fp.write(json.dumps(asdict(run)) + "\n")
        self._runs_fp.flush()
        return run

    def _write_attempt(
        self,
        job_id: str,
        prompt_id: str,
        tier: str,
        condition: str,
        attempt: Attempt,
    ) -> None:
        stem = f"{_safe(job_id)}-{attempt.index}"
        source_path = None
        if attempt.source is not None:
            source_path = self.sources / f"{stem}.py"
            source_path.write_text(attempt.source, encoding="utf-8")
        traceback_path = None
        if attempt.traceback is not None:
            traceback_path = self.tracebacks / f"{stem}.txt"
            traceback_path.write_text(attempt.traceback, encoding="utf-8")

        record = AttemptRecord(
            run_id=self.run_id,
            job_id=job_id,
            prompt_id=prompt_id,
            tier=tier,
            condition=condition,
            attempt_index=attempt.index,
            generator=attempt.generator,
            escalated=attempt.escalated,
            source_path=_rel(source_path, self.root),
            traceback_path=_rel(traceback_path, self.root),
        )
        self._attempts_fp.write(json.dumps(asdict(record)) + "\n")
        self._attempts_fp.flush()

    def write_manifest(self, manifest: dict[str, Any]) -> None:
        (self.root / "run.json").write_text(
            json.dumps(manifest, indent=2, default=str), encoding="utf-8"
        )

    def write_metrics(self, metrics: dict[str, Any]) -> None:
        (self.root / "metrics.json").write_text(
            json.dumps(metrics, indent=2, default=str), encoding="utf-8"
        )

    def write_json(self, filename: str, obj: Any) -> None:
        """Write an arbitrary JSON sidecar into the run directory (e.g. control token
        accounting), so run-specific extras land next to the attempts they describe."""

        (self.root / filename).write_text(
            json.dumps(obj, indent=2, default=str), encoding="utf-8"
        )

    def close(self) -> None:
        self._attempts_fp.close()
        self._runs_fp.close()

    def __enter__(self) -> "RecordStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def load_attempts(run_root: Path) -> list[AttemptRecord]:
    """Re-read persisted attempts for the taxonomy / analysis passes."""

    path = Path(run_root) / "attempts.jsonl"
    out: list[AttemptRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(AttemptRecord(**json.loads(line)))
    return out


def load_runs(run_root: Path) -> list[RunRecord]:
    path = Path(run_root) / "runs.jsonl"
    out: list[RunRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(RunRecord(**json.loads(line)))
    return out


def _synthetic_single_attempt(result: JobResult) -> list[Attempt]:
    """A render job (or a server that returns no trace) still has one attempt.

    We never drop the raw source/traceback just because the trace array was empty —
    that would defeat task 2.6. Reconstruct a single attempt from the top-level
    ``source`` and, on failure, the traceback the specs promise ``job_result`` carries.
    """

    traceback = None
    if result.state is JobState.FAILED:
        traceback = str(result.raw.get("traceback") or result.raw.get("error") or "")
        traceback = traceback or None
    return [
        Attempt(
            index=0,
            generator=result.raw.get("generator"),
            source=result.source,
            traceback=traceback,
            escalated=bool(result.raw.get("escalated", False)),
        )
    ]


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def _rel(path: Path | None, root: Path) -> str | None:
    return str(path.relative_to(root)) if path is not None else None
