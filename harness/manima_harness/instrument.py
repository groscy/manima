"""Instrumentation (section 4).

Two audiences, two honesty rules.

**MANIMA metrics (task 4.2)** are derived *entirely from the MCP surface* — tool-call
latencies the client already timed, job-state transitions seen while polling, and cache
behaviour inferred from repeated artifact URIs. Nothing here reaches around the surface.

**Apertus metrics (task 4.1)** — tok/s, TTFT, VRAM high-water, queue depth — are *not*
on the MCP surface. They live in vLLM and on the GPU inside WSL2. proposal.md is
explicit: "If driving it under load requires something the MCP surface does not expose,
that is a finding about the surface — record it rather than reaching around it." So the
harness treats these as an *optional operator-provided side channel* (a vLLM
``/metrics`` endpoint, ``nvidia-smi``, ``docker ps``). When no probe is wired up, the
metric is recorded as ``unobservable`` — a finding, not a zero.

The 2-second tool-call contract (task 4.3) is checked against enqueue/status/cancel
call latencies — the *tool call*, never the render duration, which is exactly the
decoupling the async job protocol exists to provide (specs/jobs).
"""

from __future__ import annotations

import subprocess
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .contract import JobState, TimedCall

# Tool calls that must return "immediately" per the specs. Render duration is excluded
# by construction: these are the enqueue/observe calls, not the work.
FAST_TOOLS = frozenset(
    {"render_animation", "generate_animation", "job_status", "job_result", "cancel_job"}
)
LATENCY_CONTRACT_S = 2.0


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile. Returns None for an empty series."""

    if not values:
        return None
    ordered = sorted(values)
    if pct <= 0:
        return ordered[0]
    if pct >= 100:
        return ordered[-1]
    rank = max(1, round((pct / 100.0) * len(ordered)))
    return ordered[rank - 1]


@dataclass
class LatencyStats:
    tool: str
    count: int
    p50: float | None
    p95: float | None
    p99: float | None
    max: float | None

    @classmethod
    def of(cls, tool: str, latencies: list[float]) -> "LatencyStats":
        return cls(
            tool=tool,
            count=len(latencies),
            p50=percentile(latencies, 50),
            p95=percentile(latencies, 95),
            p99=percentile(latencies, 99),
            max=max(latencies) if latencies else None,
        )


@dataclass
class ContractViolation:
    tool: str
    latency_s: float


@runtime_checkable
class ContainerCountProbe(Protocol):
    @property
    def available(self) -> bool: ...
    def count(self) -> int | None: ...


class NullContainerProbe:
    """No container visibility: container-count-over-time is unobservable via MCP.

    Like the Apertus probes, absence is a recorded finding, not a zero — the harness
    cannot see containers through the tool surface (one container per render lives in
    WSL2, per project.md/sandbox).
    """

    available = False

    def count(self) -> int | None:
        return None


class DockerContainerProbe:
    """Count running containers via ``docker ps -q``. Operator-wired side channel."""

    available = True

    def __init__(self, name_filter: str | None = None) -> None:
        # A label/name filter narrows the count to MANIMA's render containers rather
        # than every container on the host.
        self._filter = name_filter

    def count(self) -> int | None:
        cmd = ["docker", "ps", "-q"]
        if self._filter:
            cmd += ["--filter", f"name={self._filter}"]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0, check=True)
            return sum(1 for line in out.stdout.splitlines() if line.strip())
        except (OSError, subprocess.SubprocessError):
            return None


class ManimaMetrics:
    """MANIMA-side observability (task 4.2).

    Latency percentiles, job-state transitions, and cache-hit rate come entirely from
    the MCP surface. Container-count-over-time does not — one container per render lives
    in WSL2 — so it is an optional sampled side channel, symmetric with ApertusMetrics.
    """

    def __init__(self, container_probe: ContainerCountProbe | None = None) -> None:
        self._calls: list[TimedCall] = []
        self._transitions: list[tuple[str, str]] = []  # (job_id, state)
        self._artifact_uris: list[str] = []
        self._container_probe = container_probe or NullContainerProbe()
        self._container_samples: list[tuple[float, int]] = []  # (monotonic_t, count)

    def observe_calls(self, calls: list[TimedCall]) -> None:
        """Drain a client's timed calls into the aggregate."""

        self._calls.extend(calls)

    def observe_state(self, job_id: str, state: JobState) -> None:
        """Record a job-state transition seen while polling job_status."""

        if not self._transitions or self._transitions[-1] != (job_id, state.value):
            self._transitions.append((job_id, state.value))

    def observe_artifact(self, artifact_uri: str | None) -> None:
        if artifact_uri:
            self._artifact_uris.append(artifact_uri)

    def sample_containers(self, monotonic_t: float) -> None:
        """Tick the container-count side channel (called by the background sampler)."""

        if not self._container_probe.available:
            return
        count = self._container_probe.count()
        if count is not None:
            self._container_samples.append((monotonic_t, count))

    @property
    def container_observable(self) -> bool:
        return self._container_probe.available

    def peak_container_count(self) -> int | None:
        return max((c for _, c in self._container_samples), default=None)

    # -- derived ----------------------------------------------------------------

    def latency_by_tool(self) -> dict[str, LatencyStats]:
        by_tool: dict[str, list[float]] = {}
        for call in self._calls:
            by_tool.setdefault(call.tool, []).append(call.latency_s)
        return {tool: LatencyStats.of(tool, lat) for tool, lat in by_tool.items()}

    def latency_contract_violations(self) -> list[ContractViolation]:
        """Task 4.3: every fast tool call must return within 2 s.

        A non-empty list is a bug in MANIMA's async contract, found by the harness
        doing its job — not a harness error.
        """

        return [
            ContractViolation(tool=c.tool, latency_s=c.latency_s)
            for c in self._calls
            if c.tool in FAST_TOOLS and c.latency_s > LATENCY_CONTRACT_S
        ]

    def cache_hit_rate(self) -> float | None:
        """Fraction of successful artifacts that reused an already-seen artifact URI.

        Content-addressing means an identical request resolves to the same URI without
        re-rendering (specs/render). Repeated URIs across jobs are the observable
        signature of a cache hit from the client's side.
        """

        if not self._artifact_uris:
            return None
        seen: set[str] = set()
        hits = 0
        for uri in self._artifact_uris:
            if uri in seen:
                hits += 1
            else:
                seen.add(uri)
        return hits / len(self._artifact_uris)

    def state_transitions(self) -> list[tuple[str, str]]:
        return list(self._transitions)

    def summary(self) -> dict:
        return {
            "latency_by_tool": {
                tool: vars(stats) for tool, stats in self.latency_by_tool().items()
            },
            "latency_contract_s": LATENCY_CONTRACT_S,
            "latency_contract_violations": [
                vars(v) for v in self.latency_contract_violations()
            ],
            "cache_hit_rate": self.cache_hit_rate(),
            "distinct_states_seen": sorted({s for _, s in self._transitions}),
            "state_transition_count": len(self._transitions),
            "container_count": (
                {
                    "observable": True,
                    "samples": len(self._container_samples),
                    "peak": self.peak_container_count(),
                }
                if self.container_observable
                else {
                    "observable": False,
                    "finding": (
                        "Container-count-over-time is not on the MCP surface. Wire a "
                        "'docker ps' probe (--docker) to collect it; absence is a "
                        "finding about the surface, not a zero."
                    ),
                }
            ),
        }


# --- Apertus side channel ------------------------------------------------------
# Not on the MCP surface. Optional, operator-wired, and honest about absence.


@dataclass
class ApertusSample:
    vram_mb: float | None = None
    queue_depth: float | None = None
    # Monotonic vLLM counters; tok/s is a delta between samples (computed in aggregate).
    generation_tokens_total: float | None = None
    prompt_tokens_total: float | None = None


@runtime_checkable
class ApertusProbe(Protocol):
    @property
    def available(self) -> bool: ...
    def sample(self) -> ApertusSample: ...


class NullApertusProbe:
    """No side channel wired up: every Apertus metric is unobservable via MCP.

    This is the default, and it is a *finding*, not a failure — the harness records
    that these metrics require access the public surface does not grant.
    """

    available = False

    def sample(self) -> ApertusSample:
        return ApertusSample()


class VllmPrometheusProbe:
    """Scrape a vLLM ``/metrics`` (Prometheus text) endpoint the operator exposes.

    vLLM reports OpenAI-compatible serving metrics; the names below match its standard
    exposition. Stdlib-only (urllib) so the harness pulls in no HTTP dependency.
    """

    available = True

    def __init__(self, metrics_url: str, timeout_s: float = 1.0) -> None:
        self._url = metrics_url
        self._timeout = timeout_s

    def sample(self) -> ApertusSample:
        try:
            with urllib.request.urlopen(self._url, timeout=self._timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
        except OSError:
            # A transient scrape failure is not fatal to the profile run.
            return ApertusSample()
        metrics = _parse_prometheus(text)
        return ApertusSample(
            queue_depth=metrics.get("vllm:num_requests_waiting"),
            generation_tokens_total=metrics.get("vllm:generation_tokens_total"),
            prompt_tokens_total=metrics.get("vllm:prompt_tokens_total"),
        )


class NvidiaSmiVramProbe:
    """Sample GPU VRAM via ``nvidia-smi`` on the host. Composable with a vLLM probe."""

    available = True

    def __init__(self, gpu_index: int = 0) -> None:
        self._gpu = gpu_index

    def sample(self) -> ApertusSample:
        try:
            out = subprocess.run(
                [
                    "nvidia-smi",
                    f"--id={self._gpu}",
                    "--query-gpu=memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=True,
            )
            return ApertusSample(vram_mb=float(out.stdout.strip().splitlines()[0]))
        except (OSError, ValueError, subprocess.SubprocessError):
            return ApertusSample()


class CompositeApertusProbe:
    """Merge several probes into one sample (e.g. vLLM metrics + nvidia-smi VRAM).

    Later probes override earlier ones only on fields they actually populate, so a vLLM
    probe (queue depth, tokens) and an nvidia-smi probe (VRAM) compose without clobber.
    """

    def __init__(self, probes: list[ApertusProbe]) -> None:
        self._probes = probes

    @property
    def available(self) -> bool:
        return any(p.available for p in self._probes)

    def sample(self) -> ApertusSample:
        merged = ApertusSample()
        for probe in self._probes:
            s = probe.sample()
            merged = ApertusSample(
                vram_mb=s.vram_mb if s.vram_mb is not None else merged.vram_mb,
                queue_depth=s.queue_depth if s.queue_depth is not None else merged.queue_depth,
                generation_tokens_total=s.generation_tokens_total
                if s.generation_tokens_total is not None
                else merged.generation_tokens_total,
                prompt_tokens_total=s.prompt_tokens_total
                if s.prompt_tokens_total is not None
                else merged.prompt_tokens_total,
            )
        return merged


class ApertusMetrics:
    """Aggregate Apertus side-channel samples over a profile run (task 4.1)."""

    def __init__(self, probe: ApertusProbe | None = None) -> None:
        self._probe = probe or NullApertusProbe()
        self._samples: list[tuple[float, ApertusSample]] = []  # (monotonic_t, sample)

    @property
    def available(self) -> bool:
        return self._probe.available

    def sample(self, monotonic_t: float) -> None:
        self._samples.append((monotonic_t, self._probe.sample()))

    def vram_high_water_mb(self) -> float | None:
        vals = [s.vram_mb for _, s in self._samples if s.vram_mb is not None]
        return max(vals) if vals else None

    def peak_queue_depth(self) -> float | None:
        vals = [s.queue_depth for _, s in self._samples if s.queue_depth is not None]
        return max(vals) if vals else None

    def mean_generation_tok_per_s(self) -> float | None:
        """tok/s from the first and last generation-token counters over elapsed time."""

        pts = [
            (t, s.generation_tokens_total)
            for t, s in self._samples
            if s.generation_tokens_total is not None
        ]
        if len(pts) < 2:
            return None
        (t0, c0), (t1, c1) = pts[0], pts[-1]
        elapsed = t1 - t0
        return (c1 - c0) / elapsed if elapsed > 0 else None

    def summary(self) -> dict:
        if not self.available:
            return {
                "observable": False,
                "finding": (
                    "Apertus metrics (tok/s, TTFT, VRAM high-water, queue depth) are "
                    "not exposed by the MCP surface. Wire a vLLM /metrics probe and an "
                    "nvidia-smi probe to collect them; their absence is itself a "
                    "finding about the surface (proposal.md, Scope/Out)."
                ),
                # TTFT is unobservable even with the default probes; vLLM histograms
                # expose it, but that is an explicit operator opt-in.
                "ttft_s": None,
            }
        return {
            "observable": True,
            "samples": len(self._samples),
            "vram_high_water_mb": self.vram_high_water_mb(),
            "peak_queue_depth": self.peak_queue_depth(),
            "mean_generation_tok_per_s": self.mean_generation_tok_per_s(),
            "ttft_s": None,  # requires vLLM latency histograms; not sampled by default
        }


def _parse_prometheus(text: str) -> dict[str, float]:
    """Minimal Prometheus text parser: last value wins per bare metric name.

    Ignores labels — adequate for single-model single-replica vLLM where each metric
    has one series. A multi-series deployment would need label-aware parsing.
    """

    out: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        head, _, value = line.rpartition(" ")
        name = head.split("{", 1)[0].strip()
        if not name:
            continue
        try:
            out[name] = float(value)
        except ValueError:
            continue
    return out
