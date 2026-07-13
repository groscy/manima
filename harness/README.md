# Apertus load-test harness

External load-test harness for **MANIMA** (OpenSpec change `001-apertus-load-harness`).
It is an ordinary MCP client: it drives the server through its public tool surface
exactly as any client would, with **no privileged access, no special endpoints, and no
hooks into server internals**. If driving MANIMA under load needs something the MCP
surface doesn't expose, that is recorded as a *finding about the surface*, not worked
around.

## Status: scaffolding, not yet runnable end-to-end

The harness is a client of a working MANIMA server, and **MANIMA does not exist yet**
(see `tasks.md` §0 — the prerequisites are explicitly "not this change"). This tree is
the harness built against the documented contract in `openspec/specs`, ready to run the
moment a MANIMA server can be spawned. Until then:

- **Offline and working now:** `prompts` (the graded suite + its correctness
  annotations) and `report` (the whole section-5 analysis pipeline). Both run with no
  server — see the smoke path below.
- **Needs a live MANIMA + `mcp`:** `run` (load profiles) and `control` (frontier
  condition). They will fail at `connect(...)` until a server exists. That is expected.

Wire-detail assumptions the real server will confirm or refute are marked `ASSUMPTION`
in `manima_harness/contract.py`.

## Install

```bash
pip install -e .              # core: mcp + pyyaml
pip install -e ".[frontier]"  # + anthropic, for the control condition only
pip install -e ".[dev]"       # + ruff/pytest/pip-tools, the CI/lint toolchain
```

`prompts` and `report` need only `pyyaml`; `mcp` is required only for `run`/`control`.

CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) compiles this package and
runs `ruff` on every push/PR. There is no unit suite yet, so CI treats an empty `pytest`
collection as a pass rather than fabricate one — the offline `prompts`/`report` paths are
exercised by hand (see below) until a live MANIMA makes an end-to-end suite runnable.

## Commands

```bash
# Validate and summarise the prompt suite (offline)
python -m manima_harness prompts

# Drive a load profile (needs a spawnable MANIMA server)
python -m manima_harness run soak        --duration 3600
python -m manima_harness run burst       --concurrency 8 --waves 3
python -m manima_harness run repair-heavy --repeats 2
python -m manima_harness run mixed       --concurrency 4 --rounds 2

# Frontier control condition — same suite, submitted via render_animation
ANTHROPIC_API_KEY=... python -m manima_harness control --manim-version <pinned>

# Build the analysis report from one or more run directories (offline)
python -m manima_harness report runs/burst-* --out report.md
```

### Pointing at the server

MANIMA runs in WSL2; the harness is Windows-native (project.md). Set the stdio launch
command via a config file (`--config`) or env:

```bash
export MANIMA_SERVER_COMMAND=wsl.exe
export MANIMA_SERVER_ARGS="-d Ubuntu -- python -m manima_server"
```

### Apertus metrics side channel

tok/s, TTFT, VRAM high-water, and queue depth are **not on the MCP surface** — they live
in vLLM and on the GPU. Wire them in explicitly, or they are reported as `unobservable`
(a finding, not a zero):

```bash
python -m manima_harness run burst --vllm-metrics http://localhost:8000/metrics --nvidia-smi
```

## Layout

```
manima_harness/
  contract.py     the MCP tool surface as types + defensive parsers (mcp-free)
  config.py       server launch, polling, quality, repair budget
  client.py       the stdio MCP client + poll-to-terminal (needs mcp)
  record.py       per-attempt persistence — raw source + traceback (task 2.6)
  prompts/        the graded suite (easy/medium/hard YAML) + loader (section 1)
  generators/     SourceGenerator port + Anthropic frontier adapter (section 3)
  profiles/       soak / burst / repair-heavy / mixed load shapes (section 2)
  control.py      the frontier control condition run mode (section 3)
  instrument.py   MANIMA metrics (from the surface) + Apertus side channel (section 4)
  analysis/       success / convergence / taxonomy / throughput / report (section 5)
  __main__.py     CLI
```

## What is deliberately not here

- MANIMA itself (§0) — a different, larger change that must come first.
- Running the suite and hand-classifying results (§3 execution, §4.3, §5, §6) — those
  need a live MANIMA + Apertus + a frontier API and human judgement, so the code is in
  place but the *findings* are not, and cannot be, produced yet.
