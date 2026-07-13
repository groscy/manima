# Build the MANIMA server

## Why

MANIMA is the product — a local-first MCP server that renders Manim CE animations and
optionally generates the source locally with Apertus 8B — and **it does not exist as
code yet**. The four capability specs (`render`, `generate`, `jobs`, `sandbox`) are
authored, the architecture is documented (arc42), and an external load-test harness
(change `001-apertus-load-harness`) already sits ready to drive it. Everything points at
a server that has not been built. This change builds it, so the specs become running
behaviour and the harness has something to hammer.

## What Changes

- **New Python package `manima_server/`** implementing the MCP stdio server, structured
  as hexagonal ports/adapters (`core/ports/`, `adapters/`) per `project.md` — the core
  imports no adapter.
- **`render_animation`** (thin path): validate → sandbox-render caller-supplied Manim CE
  source → content-addressed artifact. No generator involved.
- **`generate_animation`** (thick path): Apertus 8B behind an `AnimationGenerator` port,
  Qdrant grounding injection, 240p single-frame probe render as a mechanical oracle,
  bounded repair loop, and triple-gated deny-by-default escalation.
- **Async job protocol**: `job_status`, `job_result`, `cancel_job` over a defined state
  machine, with per-job structured traces and TTL reaping.
- **Sandbox**: one rootless Docker container per render — `--network=none`,
  `--cap-drop=ALL`, read-only rootfs, restricted seccomp, memory/CPU/wall-clock limits,
  TeX shell-escape disabled. The server fails to start, loudly, if the Docker daemon is
  unreachable. AST validation runs first as a fast-fail, **not** as a security boundary.
- **Pinned Manim CE version** in one place, flowing into the render image, the grounding
  corpus, and the artifact hash.
- **Deployment**: server + inference + sandbox live in WSL2; the artifact store lives on
  the WSL2 filesystem. Only an MCP client is Windows-native.

## Capabilities

The four capability specs already exist under `openspec/specs/` as authored intent, but
OpenSpec reports `requirementCount: 0` for each — they use delta-style
`## ADDED Requirements` headers in the baseline location, so the tool does not recognise
them as realised baseline requirements. This change **delivers** all four: the spec
deltas here restate them in proper form so that archiving publishes clean baselines and
the count-0 discrepancy is resolved. No requirement's *intent* changes — this is the
implementation of already-agreed behaviour, transcribed faithfully.

### New Capabilities
- `render`: the `render_animation` tool — sandboxed execution of caller-supplied Manim CE
  source, full TeX Live, content-addressed artifacts.
- `generate`: the `generate_animation` tool — grounded local generation, probe-verified,
  bounded repair, deny-by-default escalation, generator behind a port.
- `jobs`: the asynchronous job protocol — `job_status` / `job_result` / `cancel_job`, the
  job state machine, honest traces, TTL reaping.
- `sandbox`: containment of untrusted execution — rootless Docker, no network, resource
  limits, dropped privileges, AST validation as a fast-fail.

### Modified Capabilities
- _None._ This change realises the existing specs; it does not alter their requirements.

## Impact

- **New code**: `manima_server/` (core + ports + adapters), a pinned Manim CE + TeX Live
  render image, server entrypoint.
- **New runtime dependencies**: `mcp` SDK, Docker Desktop (WSL2 backend), vLLM serving
  Apertus 8B int4, Qdrant, Manim CE (pinned).
- **Platform**: WSL2-hosted server side; artifact store on the WSL2 filesystem.
- **Unblocks**: change `001-apertus-load-harness` — its §0 prerequisites are exactly the
  deliverables here; `run`/`control` become executable once this lands.
- **Non-negotiables enforced** (`project.md`): all execution sandboxed (ADR-001);
  escalation triple-gated (ADR-003); no unverified source reported as success (ADR-003);
  artifacts referenced, never embedded (ADR-004); static validation is not the boundary;
  `render_animation` never depends on the generator.

## Depends On
