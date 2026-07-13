## Context

MANIMA is a local-first MCP server that renders Manim Community Edition animations and,
optionally, generates the Manim source locally with Apertus 8B. The behaviour is fully
specified across four capabilities (`render`, `generate`, `jobs`, `sandbox`) and the
architecture is documented in the bundled arc42 (context, components, repair-loop,
job-lifecycle, deployment views). No server code exists yet; this design turns the specs
into a buildable system.

The environment is fixed and constraining (`project.md`): a Windows 11 desktop with a
single 16 GB-VRAM NVIDIA GPU. vLLM and Linux containers are WSL2-only on Windows, so the
**entire server side runs in WSL2** — MCP server, vLLM, Docker sandbox, Qdrant, and the
artifact store — while only an MCP client is Windows-native. The six non-negotiables in
`project.md` (ADR-001/003/004) are hard invariants, not preferences.

The consumer already exists: change `001-apertus-load-harness` drives this server through
its public MCP surface and will validate it under load once it runs.

## Goals / Non-Goals

**Goals:**
- Implement the four capability specs exactly, with the async job protocol as the spine.
- Ports/adapters layout where the **core imports no adapter**, so the generator, sandbox,
  store, and grounding are all swappable and the core is testable without Docker or a GPU.
- Make `render_animation` fully functional independent of the generator (invariant 6).
- Enforce containment structurally: no code path executes Manim source on the host.
- Single source of truth for the pinned Manim CE version, flowing into image, corpus, and
  artifact hash.

**Non-Goals:**
- The load-test harness (change 001) — a separate, external client.
- Hardened multi-tenant isolation. WSL2 containment is weaker than native rootless Docker;
  the design states this plainly rather than implying otherwise.
- Distributed/multi-GPU serving, a hosted control plane, or a web UI.
- Semantic verification of generated scenes. The probe is a syntax/API oracle only; the
  server never claims a scene is *correct*, only that it *runs*.

## Decisions

### D1: Hexagonal core with explicit ports

Ports (in `core/ports/`), each a Protocol/ABC the core depends on:
- `AnimationGenerator` — `generate(prompt, grounding, repair_context) -> source`. Adapters:
  `ApertusVLLMGenerator` (local), `EscalationGenerator` (hosted, deny-by-default).
- `SandboxExecutor` — `run(source, mode: probe|full, limits) -> RenderOutcome`. Adapter:
  `DockerSandbox`.
- `GroundingRetriever` — `retrieve(prompt, k) -> snippets`. Adapter: `QdrantGrounding`.
- `ArtifactStore` — content-addressed put/get + TTL reap. Adapter: `FsArtifactStore`.
- `JobStore` — durable job records, state, trace. Adapter: `SqliteJobStore`.

The core (job manager, repair loop, escalation gate, hashing) orchestrates ports and
imports no adapter. **Why:** invariant 6 and swappability (specs/generate: "generator is
swapped" with no core change) fall out of this for free, and the core becomes unit-testable
with fakes. *Alternative — a layered service with direct dependencies:* rejected; it would
couple the repair loop to vLLM and Docker and make the "generator proves inadequate → still
renders" degradation a special case rather than the default.

### D2: Async job manager; tools enqueue and return within 2 s

Every tool (`render_animation`, `generate_animation`) validates arguments, creates a job
record in `QUEUED`, hands it to an in-process asyncio job manager, and returns a `job_id`
immediately. A bounded pool of workers advances jobs through the state machine. `job_status`
reads the record (never blocks); `job_result` reads it in terminal states only. **Why:**
specs/jobs requires tool calls to return within 2 s regardless of render duration. *Alt —
synchronous render with a timeout:* rejected; it violates the async contract and would let
a long render wedge the stdio transport.

Concurrency is capped by a semaphore sized to the machine, separated by phase: generation
(GPU/VRAM-bound, shares the GPU with vLLM) is limited more tightly than rendering
(CPU/container-bound). **Why:** a burst of `generate` calls contends with vLLM for the same
16 GB; unbounded fan-out OOMs the GPU.

### D3: Sandbox — one rootless Docker container per render, fail-loud

Each render (probe or full, generated or operator-supplied) runs in a fresh container:
`--network=none`, `--cap-drop=ALL`, `--read-only` rootfs, non-root user, restricted seccomp,
`--memory` / `--cpus` / wall-clock timeout, TeX shell-escape disabled. Probe and full renders
carry **separate timeout budgets**. If the Docker daemon is unreachable at startup, the
server **fails to start, loudly**, and never falls back to host execution. **Why:**
invariants 1 and 5, and the whole sandbox spec. *Alt — gVisor/Firecracker/nsjail:* stronger,
but not reliably available under Docker Desktop on WSL2; recorded as a future hardening path.
The honest containment story: the WSL2 VM boundary is the primary containment, container
controls are defence-in-depth inside it (`project.md`).

### D4: Generate pipeline — ground → generate → AST-validate → probe → repair → full

1. Retrieve top-k grounding for the pinned CE version from Qdrant; inject into the prompt.
2. Generate a candidate via the `AnimationGenerator` port.
3. AST-validate against an allowlist (fast-fail, structured rejection the repair loop reads).
   **Not** a security boundary (invariant 5) — the sandbox is.
4. Probe-render: 240p, single frame, in the sandbox, as a mechanical correctness oracle.
5. On probe/validation failure with budget remaining: feed source + traceback back as repair
   context, return the job to `GENERATING`, increment attempt. Bounded by `repair_budget`.
6. On probe success: full-quality render → content-addressed artifact.

**Why:** this is specs/generate verbatim; the probe is what converts an unreliable local
model into an honest output contract. A `SUCCEEDED` job means the scene actually rendered.

### D5: Escalation — triple-gated, deny-by-default, receipted

Escalation to a hosted model fires only when **all three** hold: server config permits it,
the call passed `allow_escalation: true`, and the local repair budget is exhausted (ADR-003).
It emits a receipt (job id, model, token counts, reason). With the gate closed the server is
fully functional and attempts no egress — verifiable by running air-gapped. **Why:**
sovereignty is the point of the local path; escalation is an explicit, audited exception.

### D6: Content-addressed store keyed by `(source, quality, manim_version)`

Artifact key = hash of the exact source, quality, and pinned Manim version. Identical
requests dedupe to the existing artifact without re-rendering; a version bump cannot collide
with prior artifacts because the version participates in the hash. Artifacts live on the WSL2
filesystem (not `/mnt/c`) and are TTL-reaped, transitioning the job to `EXPIRED`. **Why:**
specs/render + specs/jobs; and cross-boundary I/O to `/mnt/c` is slow enough to matter for
multi-megabyte video (`project.md`).

### D7: Durable job state in SQLite (on the WSL2 filesystem)

Job records, state, attempt count, and the structured trace persist in SQLite. **Why:**
`job_result` must survive across the job's life and report honest traces; SQLite gives
durability, TTL queries, and zero external service. *Alt — in-memory dict:* simplest, but
loses all jobs on restart and complicates TTL reaping. *Alt — Redis:* another daemon to run
in WSL2 for no benefit at this scale.

### D8: Version pinning as a single constant

The pinned Manim CE version is defined once and consumed by the render image build, the
grounding corpus build, and the artifact hash. Bumping it means rebuilding all three, in that
order (image → corpus → hash). **Why:** `project.md` conventions; drift between these three is
the exact failure mode grounding exists to prevent.

## Risks / Trade-offs

- **16 GB VRAM is tight.** Apertus 8B int4 (~6 GB) plus the KV cache of a long grounded
  prompt, sharing the GPU with concurrent generations → OOM. **Mitigation:** int4 quant, a
  prompt/grounding token budget, and a tight generation-concurrency semaphore (D2). The
  harness measures the actual headroom.
- **WSL2 sandbox is weaker than native rootless Docker.** → State it plainly; treat the WSL2
  VM boundary as primary containment; keep container controls as defence-in-depth (D3).
- **Repair loop may not converge** — several generations per animation for no gain. → Bounded
  budget; the trace records every attempt so convergence is measurable, and change 001 turns
  "no improvement" into a finding, not a knob to raise.
- **`/mnt/c` I/O is slow.** → Store and job DB stay on the WSL2 filesystem (D6/D7).
- **Docker daemon down or wrong.** → Fail-loud at startup, never host-execute (D3).
- **Manim CE / ManimGL drift** poisons an 8B model's output. → Grounding + probe + repair are
  load-bearing, not polish; the pinned corpus is the lever if failures are API-confusion.

## Migration Plan

Greenfield — nothing to migrate. Bring-up order:
1. Build the pinned Manim CE + full TeX Live render image.
2. Start Docker (verify daemon reachable; server refuses to start otherwise).
3. Stand up vLLM serving Apertus 8B int4 (OpenAI-compatible endpoint).
4. Build the grounding corpus from the pinned version; load into Qdrant.
5. Start the MCP server (stdio).

**Rollback / degradation:** the generator sits behind a port and is deny-by-default, so a
broken or unavailable generator leaves `render_animation` fully functional — the architecture
degrades gracefully rather than failing entirely (invariant 6, specs/generate).

## Open Questions

- Exact Apertus 8B checkpoint and int4 method (AWQ vs GPTQ)? Affects the vLLM adapter and VRAM
  budget.
- Which Manim CE version is pinned? Everything in D8 keys off it.
- Generation-concurrency cap: what N keeps generate + vLLM within 16 GB under burst?
- Escalation adapter target — which hosted model/provider, and how is its key supplied
  (env-only, never in tool args)?
- Default TTL retention window for artifacts and job logs?
- Job store: is cross-restart durability actually required for v1, or is in-memory acceptable
  until the harness needs durable traces? (Leaning SQLite per D7.)
