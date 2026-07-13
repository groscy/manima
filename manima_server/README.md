# MANIMA server

Local-first MCP server that **renders** Manim CE animations and, optionally, **generates**
the source locally with Apertus 8B (OpenSpec change `build-manima-server`). Two tool
surfaces, neither privileged: `render_animation` (thin — caller supplies source) and
`generate_animation` (thick — grounded local generation, probe-verified, bounded repair).

## Status: software built and unit-tested; live bring-up needs WSL2 + Docker + a GPU

The **pure core is implemented and tested offline** (28 passing tests, stdlib-only): the
job state machine, content-addressing, the AST validator, the escalation gate, the full
job manager (render path, generate pipeline, repair loop, escalation, cancellation) driven
end-to-end with fakes, and the TTL reaper.

The **adapters are written against real contracts** but can't be runtime-verified here —
they need infrastructure this environment doesn't have:

| Path | Needs | Verified |
|---|---|---|
| Core (domain, state machine, job manager, reaper, validator, escalation) | nothing | ✅ 28 tests |
| Sandbox (`DockerSandbox`, `docker/Dockerfile`) | Docker Desktop (WSL2) | code + image only |
| Store / jobs (`FsArtifactStore`, `SqliteJobStore`) | filesystem | ✅ tested |
| Generate (`ApertusVLLMGenerator`, `QdrantGrounding`) | vLLM + Qdrant + GPU | code only |
| Escalation (`AnthropicEscalationGenerator`) | hosted API key (env) | code only |

## Architecture

Hexagonal (design D1): ports in `manima_server/core/ports`, adapters in
`manima_server/adapters`. **The core imports no adapter** — so `render_animation` never
depends on the generator (invariant 6), and every port is swappable and fake-able.

```
manima_server/
  version.py            single pinned Manim CE version (flows to image, corpus, hash)
  config.py             sandbox limits, escalation gate, endpoints, TTL
  core/
    domain.py           JobState machine vocabulary, Job, Attempt, RenderOutcome
    state_machine.py    the transition table (repair is the only backward edge)
    hashing.py          content key = hash(source, quality, manim_version)
    validator.py        AST allowlist fast-fail (NOT the security boundary)
    escalation.py       the deny-by-default triple gate
    job_manager.py      async spine: enqueue → advance → persist; render & generate
    reaper.py           TTL: drop artifacts, expire jobs
    ports/              SandboxExecutor, ArtifactStore, GroundingRetriever,
                        AnimationGenerator, JobStore
  adapters/             DockerSandbox, FsArtifactStore, SqliteJobStore,
                        QdrantGrounding, ApertusVLLMGenerator, AnthropicEscalationGenerator
  server.py             FastMCP stdio server; the five tools
docker/Dockerfile       pinned Manim CE + full TeX Live render image
scripts/                build_corpus.py, bringup.sh
```

## Install

```bash
pip install -e .                    # core + render path (mcp)
pip install -e ".[generate]"        # + vLLM/Qdrant clients for generate
pip install -e ".[escalation]"      # + hosted-model SDK for escalation
pip install -e ".[dev]" && pytest   # run the offline test suite
```

## The five tools

- `render_animation(source, quality?, scene_name?)` → `{job_id}`
- `generate_animation(prompt, quality?, repair_budget?, allow_escalation?)` → `{job_id}`
- `job_status(job_id)` → `{state, attempt, phase}` (cheap, non-blocking)
- `job_result(job_id)` → terminal-only: `{artifact_uri, source, trace}` (or expiry)
- `cancel_job(job_id)` → kills a running job; no-op on a terminal one

Every call returns within 2 s regardless of render duration — the job manager does the slow
work on a background task (specs/jobs).

## Bring-up

`scripts/bringup.sh` runs the ordered sequence (design Migration Plan): build image →
verify Docker → start vLLM → build corpus/Qdrant → start server. The render path is live
after the Docker step; the generate path needs vLLM + Qdrant.

Set `MANIMA_RENDER_ONLY=1` for a sovereign render-only deployment that imports no
generate-path dependency at all.

## Non-negotiables (enforced structurally, per `openspec/project.md`)

1. **All execution sandboxed** — every render goes through `SandboxExecutor`; no host path.
2. **Escalation deny-by-default** — the triple gate is one pure predicate (`core/escalation`).
3. **No unverified success** — `SUCCEEDED` means the probe/full render actually ran.
4. **Artifacts referenced, never embedded** — the store returns paths.
5. **Static validation is not the boundary** — the sandbox is; the validator is a fast-fail.
6. **`render_animation` never depends on the generator** — the core imports no adapter.

## Unblocks

Change `001-apertus-load-harness` — once this server can be spawned, point the harness's
`MANIMA_SERVER_COMMAND`/`ARGS` at `python -m manima_server.server` (harness task 12.4).
