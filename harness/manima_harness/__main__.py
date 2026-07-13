"""CLI entry point.

Four subcommands:

    prompts   validate / list the suite            offline, needs no server
    run       drive a load profile against MANIMA  needs a running server
    control   run the frontier control condition   needs a server + ANTHROPIC_API_KEY
    report    build the analysis report from runs  offline, reads run dirs

``prompts`` and ``report`` run with no server and are the parts of this harness that
are meaningful before MANIMA exists — a way to sanity-check the suite and the analysis
pipeline against fixtures. ``run`` and ``control`` need a spawnable MANIMA server; until
one exists they will fail at ``connect``, which is expected (tasks.md sequencing note).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import HarnessConfig
from .instrument import (
    ApertusMetrics,
    ApertusProbe,
    CompositeApertusProbe,
    DockerContainerProbe,
    ManimaMetrics,
    NvidiaSmiVramProbe,
    VllmPrometheusProbe,
)
from .prompts import Tier, load_suite
from .record import RecordStore


def main(argv: list[str] | None = None) -> int:
    # Reports contain non-ASCII glyphs (⚠, —). The default Windows console is cp1252
    # and would crash on print(); force UTF-8 so `report` works in a plain terminal.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manima-harness", description=__doc__)
    sub = parser.add_subparsers(dest="command")

    # -- prompts ----------------------------------------------------------------
    p_prompts = sub.add_parser("prompts", help="validate and list the prompt suite")
    p_prompts.add_argument("--tier", choices=[t.value for t in Tier], action="append")
    p_prompts.set_defaults(func=_cmd_prompts)

    # -- run --------------------------------------------------------------------
    p_run = sub.add_parser("run", help="drive a load profile against MANIMA")
    p_run.add_argument("profile", choices=["soak", "burst", "repair-heavy", "mixed"])
    _add_common_run_args(p_run)
    p_run.add_argument("--concurrency", type=int, default=4, help="burst/mixed concurrency")
    p_run.add_argument("--waves", type=int, default=1, help="burst waves")
    p_run.add_argument("--rounds", type=int, default=1, help="mixed rounds")
    p_run.add_argument("--repeats", type=int, default=1, help="repair-heavy repeats")
    p_run.add_argument("--duration", type=float, default=None, help="soak duration (s)")
    p_run.add_argument("--max-iterations", type=int, default=None, help="soak iteration cap")
    p_run.set_defaults(func=_cmd_run)

    # -- control ----------------------------------------------------------------
    p_ctl = sub.add_parser("control", help="run the frontier control condition")
    _add_common_run_args(p_ctl)
    p_ctl.add_argument("--model", default=None, help="frontier model id override")
    p_ctl.add_argument("--manim-version", default="unpinned", help="CE version to target")
    p_ctl.set_defaults(func=_cmd_control)

    # -- report -----------------------------------------------------------------
    p_report = sub.add_parser("report", help="build the analysis report from run dirs")
    p_report.add_argument("run_dir", nargs="+", type=Path)
    p_report.add_argument("--out", type=Path, default=None, help="write markdown here")
    p_report.set_defaults(func=_cmd_report)

    return parser


def _add_common_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", type=Path, default=None, help="harness config JSON")
    p.add_argument("--tier", choices=[t.value for t in Tier], action="append")
    p.add_argument("--out-dir", type=Path, default=None, help="run output root")
    p.add_argument("--vllm-metrics", default=None, help="vLLM /metrics URL (Apertus probe)")
    p.add_argument("--nvidia-smi", action="store_true", help="sample VRAM via nvidia-smi")
    p.add_argument("--docker", action="store_true", help="sample container count via docker ps")
    p.add_argument("--docker-filter", default=None, help="name filter for the docker probe")


# -- commands -------------------------------------------------------------------


def _cmd_prompts(args: argparse.Namespace) -> int:
    tiers = _tiers(args.tier)
    suite = load_suite(tiers)  # load_suite validates (task 1.4 enforced)
    print(f"Prompt suite: {len(suite)} prompts")
    for tier in tiers or list(Tier):
        rows = suite.by_tier(tier)
        highrisk = sum(1 for p in rows if p.manimgl_risk.value == "high")
        print(f"  {tier.value:6s}  {len(rows):2d} prompts  ({highrisk} high manimgl-risk)")
    print(f"Repair-heavy selection: {len(suite.high_manimgl_risk())} high-risk prompts")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    import anyio

    from .client import connect
    from .profiles import build_profile

    config = _config(args)
    suite = load_suite(_tiers(args.tier))
    probe = _apertus_probe(args)
    run_id = _run_id(args.profile)
    store = RecordStore(args.out_dir or config.out_dir, run_id)
    manima = ManimaMetrics(_container_probe(args))
    apertus = ApertusMetrics(probe)

    profile_kwargs = _profile_kwargs(args.profile, args)
    profile = build_profile(
        args.profile,
        config=config,
        suite=suite,
        store=store,
        manima_metrics=manima,
        apertus_metrics=apertus,
        **profile_kwargs,
    )

    async def drive() -> list:
        async with connect(config) as client:
            return await profile.run(client)

    try:
        runs = anyio.run(drive)
    finally:
        _finalize(store, manima, apertus, run_id, args.profile, profile_kwargs)
    print(f"[{run_id}] {len(runs)} jobs; artifacts under {store.root}")
    return 0


def _cmd_control(args: argparse.Namespace) -> int:
    import anyio

    from .client import connect
    from .control import ControlCondition
    from .generators.frontier import DEFAULT_MODEL, AnthropicFrontierGenerator

    config = _config(args)
    suite = load_suite(_tiers(args.tier))
    probe = _apertus_probe(args)
    run_id = _run_id("control")
    store = RecordStore(args.out_dir or config.out_dir, run_id)
    manima = ManimaMetrics(_container_probe(args))
    apertus = ApertusMetrics(probe)

    generator = AnthropicFrontierGenerator(
        model=args.model or DEFAULT_MODEL,
        manim_version=args.manim_version,
    )
    control = ControlCondition(
        config,
        suite,
        store,
        manima,
        apertus,
        generator=generator,
    )

    async def drive() -> list:
        async with connect(config) as client:
            return await control.run(client)

    try:
        runs = anyio.run(drive)
    finally:
        _finalize(store, manima, apertus, run_id, "control", {})
    print(f"[{run_id}] control: {len(runs)} jobs via {generator.identity}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from .analysis.report import build_report

    markdown = build_report(list(args.run_dir))
    if args.out:
        args.out.write_text(markdown, encoding="utf-8")
        print(f"report written to {args.out}")
    else:
        print(markdown)
    return 0


# -- shared helpers -------------------------------------------------------------


def _config(args: argparse.Namespace) -> HarnessConfig:
    return HarnessConfig.load(getattr(args, "config", None))


def _tiers(tier_values: list[str] | None) -> list[Tier] | None:
    return [Tier(v) for v in tier_values] if tier_values else None


def _run_id(profile: str) -> str:
    # datetime/uuid are fine here — this is ordinary host code, not a workflow script.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{profile}-{stamp}-{uuid.uuid4().hex[:6]}"


def _apertus_probe(args: argparse.Namespace) -> ApertusProbe | None:
    probes: list[ApertusProbe] = []
    if getattr(args, "vllm_metrics", None):
        probes.append(VllmPrometheusProbe(args.vllm_metrics))
    if getattr(args, "nvidia_smi", False):
        probes.append(NvidiaSmiVramProbe())
    if not probes:
        return None  # -> NullApertusProbe: metrics recorded as unobservable
    if len(probes) == 1:
        return probes[0]
    return CompositeApertusProbe(probes)


def _container_probe(args: argparse.Namespace):
    if getattr(args, "docker", False):
        return DockerContainerProbe(name_filter=getattr(args, "docker_filter", None))
    return None  # -> NullContainerProbe: container count recorded as unobservable


def _profile_kwargs(profile: str, args: argparse.Namespace) -> dict:
    if profile == "soak":
        return {"duration_s": args.duration, "max_iterations": args.max_iterations}
    if profile == "burst":
        return {"concurrency": args.concurrency, "waves": args.waves}
    if profile == "repair-heavy":
        return {"repeats": args.repeats}
    if profile == "mixed":
        return {"concurrency": args.concurrency, "rounds": args.rounds}
    return {}


def _finalize(
    store: RecordStore,
    manima: ManimaMetrics,
    apertus: ApertusMetrics,
    run_id: str,
    profile: str,
    profile_kwargs: dict,
) -> None:
    store.write_metrics({"manima": manima.summary(), "apertus": apertus.summary()})
    manifest = {"run_id": run_id, "profile": profile, **profile_kwargs}
    # Surface concurrency at the top level so the throughput analysis can find it.
    if "concurrency" in profile_kwargs:
        manifest["concurrency"] = profile_kwargs["concurrency"]
    store.write_manifest(manifest)
    store.close()


if __name__ == "__main__":
    sys.exit(main())
