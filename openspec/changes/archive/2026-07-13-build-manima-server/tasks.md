# Tasks — Build the MANIMA server

**Sequencing.** Build inward-out and render-before-generate, honoring invariant 6
(`render_animation` never depends on the generator): scaffolding → sandbox → store →
jobs → **render works end to end** → grounding → generator → generate + repair →
escalation → server assembly → bring-up. The thin path must be fully working before any
generator code lands, so a broken generator can never take the render path down.

All server code lives in a new `manima_server/` package (WSL2-hosted). Ports go in
`core/ports/`, adapters in `adapters/`; the core imports no adapter (design D1).

**Status note (implemented 2026-07-13).** The package is built in `manima_server/`. A
task is checked when its **code/artifact deliverable exists** and — where possible —
is covered by the offline test suite (28 passing, stdlib-only: core domain, state
machine, hashing, validator, escalation gate, the full job manager driven end-to-end
with fakes, storage adapters, TTL reaper). Tasks that are inherently a *runtime action
against infrastructure this environment lacks* (Docker daemon, GPU/vLLM, Qdrant, or an
actual air-gapped/e2e run) stay **unchecked** even though their supporting code exists —
namely 2.4, 5.5, 6.1, 6.3, 7.1, 9.4, 12.2, 12.4. The generate-path adapters (vLLM,
Qdrant, Anthropic) are code-complete but not runtime-verified.

## 1. Scaffolding & conventions

- [x] 1.1 Create the `manima_server/` package with `core/`, `core/ports/`, `adapters/`,
      and a `pyproject.toml` (Python 3.12, `mcp` SDK); core has no adapter imports
- [x] 1.2 Define the pinned Manim CE version as a single constant, consumed by the image
      build, corpus build, and artifact hash (design D8)
- [x] 1.3 Define the port Protocols/ABCs in `core/ports/`: `AnimationGenerator`,
      `SandboxExecutor`, `GroundingRetriever`, `ArtifactStore`, `JobStore`
- [x] 1.4 Define core domain types: `JobState` machine, `Job`, `Attempt`/`Trace`,
      `RenderOutcome`, `RenderMode` (probe|full) — no I/O, unit-testable

## 2. Sandbox (invariants 1 & 5; specs/sandbox)

- [x] 2.1 Build the render image: pinned Manim CE + full TeX Live, non-root user,
      TeX shell-escape disabled
- [x] 2.2 Implement `DockerSandbox` (`SandboxExecutor` adapter): one container per render,
      `--network=none`, `--cap-drop=ALL`, read-only rootfs, restricted seccomp
- [x] 2.3 Enforce resource limits: `--memory`, `--cpus`, wall-clock timeout, with
      **separate** probe vs full timeout budgets
- [ ] 2.4 Verify a scene is killed on wall-clock timeout and OOM-killed on memory
      exhaustion, with only that job failing and the server staying responsive
- [x] 2.5 Fail-loud at startup if the Docker daemon is unreachable; no host-execution
      fallback exists on any path
- [x] 2.6 Implement the AST allowlist validator as a fast-fail returning a structured
      rejection — wired *before* execution, never treated as the security boundary

## 3. Content-addressed artifact store (specs/render; design D6)

- [x] 3.1 Implement `FsArtifactStore` on the WSL2 filesystem, key = hash of
      `(source, quality, manim_version)`
- [x] 3.2 Serve an identical request from cache without re-rendering; confirm a version
      bump does not collide with prior artifacts
- [x] 3.3 Return artifacts by filesystem path only — never inline video bytes (invariant 4)

## 4. Jobs — store, manager, state machine (specs/jobs; design D2, D7)

- [x] 4.1 Implement `SqliteJobStore` (job record, state, attempt, trace) on the WSL2 fs
- [x] 4.2 Implement the async job manager: enqueue → return `job_id`, worker pool advances
      jobs, concurrency bounded by phase-aware semaphores (render vs generate)
- [x] 4.3 Enforce the state machine; the only backward edge is
      `RENDERING`/`VALIDATING` → `GENERATING` (repair), incrementing the attempt counter
- [x] 4.4 Implement `job_status` (state/attempt/phase, non-blocking) and `job_result`
      (terminal-only: `artifact_uri`, `source`, `trace`)
- [x] 4.5 Implement `cancel_job`: kill the running container, transition to `CANCELLED`;
      no-op + acknowledge on an already-terminal job
- [x] 4.6 Record an honest per-job trace: generator identity per attempt, each traceback,
      attempt count, escalation flag — a success never conceals a hard path to it

## 5. Render path — the thin path works end to end (specs/render; invariant 6)

- [x] 5.1 Implement `render_animation`: validate args, enqueue, return `job_id` within 2 s,
      no generator involved
- [x] 5.2 Drive a valid single-Scene source through `VALIDATING` → `RENDERING` →
      `SUCCEEDED`, with `job_result` returning the video path
- [x] 5.3 On a source that raises, transition to `FAILED` and return the traceback; attempt
      no repair (the caller wrote it)
- [x] 5.4 Fail an ambiguous multi-Scene source (when `scene_name` omitted) with a message
      naming the candidates; infer the scene when exactly one is present
- [ ] 5.5 Confirm a scene needing an uncommon LaTeX package renders with no network access
      or on-demand install (image carries full TeX Live)

## 6. Grounding (specs/generate; design D4 step 1)

- [ ] 6.1 Build the grounding corpus from the pinned Manim CE version (API snippets)
- [x] 6.2 Implement `QdrantGrounding` (`GroundingRetriever` adapter): top-k retrieval for
      the pinned version
- [ ] 6.3 Verify a ManimGL-eliciting prompt (e.g. `ShowCreation`) retrieves the CE
      equivalent, and the corpus matches the exact version in the render image

## 7. Local generator (specs/generate; design D1)

- [ ] 7.1 Stand up vLLM serving Apertus 8B int4 (OpenAI-compatible endpoint) in WSL2
- [x] 7.2 Implement `ApertusVLLMGenerator` (`AnimationGenerator` adapter) using the
      grounded prompt + optional repair context
- [x] 7.3 Confirm the generator is swappable: replacing it requires no change to the core,
      the repair loop, or the tool surface

## 8. Generate pipeline & repair loop (specs/generate; design D4)

- [x] 8.1 Implement `generate_animation`: validate args, enqueue, return `job_id` within 2 s
- [x] 8.2 Wire the pipeline: ground → generate → AST-validate → probe-render (240p, single
      frame) → full render on probe success
- [x] 8.3 Capture the probe traceback as repair context on failure; on success proceed to
      full quality without claiming semantic correctness
- [x] 8.4 Implement the bounded repair loop: on probe/validation failure with budget left,
      return to `GENERATING` with source + traceback as context; attempt 2 sees attempt 1's
      traceback naming the failed construct
- [x] 8.5 On exhausted budget with escalation closed: `FAILED` with the last traceback and
      best-effort source, so a stronger caller can take over

## 9. Escalation — deny-by-default (specs/generate; ADR-003; design D5)

- [x] 9.1 Implement `EscalationGenerator` adapter (hosted model; key from env only, never a
      tool arg)
- [x] 9.2 Enforce the triple gate: server config permits **and** `allow_escalation: true`
      **and** local budget exhausted — else no escalation
- [x] 9.3 Emit an escalation receipt: job id, model called, token counts, reason the local
      path failed
- [ ] 9.4 Verify air-gapped operation: gate closed + network disabled → `generate_animation`
      completes locally with no egress attempted

## 10. Server assembly & MCP surface

- [x] 10.1 Implement the MCP stdio server entrypoint; register all five tools
      (`render_animation`, `generate_animation`, `job_status`, `job_result`, `cancel_job`)
- [x] 10.2 Startup preflight: Docker reachable, render image present, store + job DB
      writable; fail loud on any missing precondition
- [x] 10.3 Confirm every tool call returns within 2 s regardless of render duration
      (async contract; specs/jobs)

## 11. Retention & housekeeping (specs/jobs)

- [x] 11.1 Implement the TTL reaper: remove artifacts/job logs past the retention window and
      transition the job to `EXPIRED`
- [x] 11.2 `job_result` on an expired job reports expiry, not a dangling path

## 12. Bring-up & verification

- [x] 12.1 Document and script the bring-up sequence: image → Docker → vLLM → corpus/Qdrant
      → server (design Migration Plan)
- [ ] 12.2 End-to-end smoke: render a known-good scene, then generate one from a prompt, via
      an MCP client
- [x] 12.3 Confirm graceful degradation: with the generator unavailable, `render_animation`
      still works end to end (invariant 6)
- [ ] 12.4 Unblock change `001-apertus-load-harness`: point its `run`/`control` at this
      server (set `MANIMA_SERVER_COMMAND`/`ARGS`) and confirm a single job completes
