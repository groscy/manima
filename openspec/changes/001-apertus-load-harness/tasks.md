# Tasks — 001 Apertus Load-Test Harness

**Sequencing note.** This depends on MANIMA existing. Build the animation tool
first — sandbox, render path, job manager, then the generate path. The harness is
a client of a working server, not a substitute for building one.

**Status note (harness scaffolding built 2026-07-13).** MANIMA does not exist yet,
so the harness cannot be run end to end. What is checked below is **code
implemented against the documented MCP contract** (`openspec/specs`), living in
`harness/` — ready to run the moment a MANIMA server can be spawned. What stays
unchecked is anything that requires *executing* against a live MANIMA + Apertus +
frontier API and then exercising human judgement on the results: the §0
prerequisites, the control *run* itself (3.3), and the whole of §6. The offline
parts (prompt suite, analysis pipeline) are verified working; the load-driving
parts compile and are wired but are unrunnable until §0 lands. Wire-detail
assumptions the real server will confirm are marked `ASSUMPTION` in
`harness/manima_harness/contract.py`.

## 0. Prerequisites (MANIMA, not this change)

- [ ] 0.1 Render sandbox operational (Docker Desktop / WSL2 backend)
- [ ] 0.2 `render_animation` working end to end
- [ ] 0.3 Async job protocol working (`job_status`, `job_result`, `cancel_job`)
- [ ] 0.4 vLLM serving Apertus 8B int4 under WSL2, OpenAI-compatible endpoint
- [ ] 0.5 Grounding corpus built from the pinned Manim CE version
- [ ] 0.6 `generate_animation` with the repair loop working

## 1. Prompt suite

- [x] 1.1 10 easy prompts (mobjects, plotting, basic LaTeX)
      — `harness/manima_harness/prompts/easy.yaml`
- [x] 1.2 10 medium prompts (transforms, updaters, multi-step)
      — `prompts/medium.yaml`
- [x] 1.3 10 hard prompts (3D, camera, matrices) — `prompts/hard.yaml`
- [x] 1.4 For each, record what a *correct* scene must contain — needed for
      semantic-failure classification, which the probe render cannot detect
      — the `expected:` list on every prompt; the loader refuses a prompt without one

## 2. Harness

- [x] 2.1 MCP client that drives the server as any client would — `client.py`
      (five documented tools + poll-to-terminal; needs `mcp` at runtime)
- [x] 2.2 Soak profile: sequential, sustained, hours — `profiles/soak.py`
- [x] 2.3 Burst profile: N concurrent, N sweepable — `profiles/burst.py`
- [x] 2.4 Repair-heavy profile: prompts selected to fail first-pass
      — `profiles/repair_heavy.py` (selects high `manimgl_risk` prompts)
- [x] 2.5 Mixed profile: interleave `render_animation` and `generate_animation`
      — `profiles/mixed.py`
- [x] 2.6 Persist raw source and raw traceback for **every attempt** — the
      taxonomy depends on reading these, not on aggregate counters
      — `record.py`; verified writing per-attempt source/traceback files offline

## 3. Control condition

- [x] 3.1 Frontier-model client generating Manim source
      — `generators/frontier.py` (Anthropic adapter behind a `SourceGenerator` port)
- [x] 3.2 Submit via `render_animation` — same sandbox, same probe, same oracle
      — `control.py` (single-pass, matching render's no-repair contract)
- [ ] 3.3 Same prompt suite, same scoring. **Do not skip.** — mechanism built
      (control runs the identical suite through the same record/analysis path); the
      *run* is blocked on §0

## 4. Instrumentation

- [x] 4.1 Apertus: tok/s, TTFT, VRAM high-water, queue depth per profile
      — `instrument.py` (vLLM `/metrics` + `nvidia-smi` side-channel probes; not on
      the MCP surface, so absent probes are recorded as a finding. TTFT needs vLLM
      latency histograms — documented as an operator opt-in, not sampled by default)
- [x] 4.2 MANIMA: tool-call latency percentiles, job state transitions,
      container count over time, cache hit rate — `instrument.ManimaMetrics`
      (first three from the surface; container count via an optional `docker ps` probe)
- [x] 4.3 Confirm tool-call latency holds under 2 s at every concurrency level —
      if it does not, the async contract is broken and that is a bug in MANIMA,
      found by the harness doing its job — `latency_contract_violations` + the 6.4
      advisory; the *confirmation across a sweep* runs once §0 lands

## 5. Analysis

- [x] 5.1 Success rates: first-pass and post-repair, per tier, per condition
      — `analysis/success.py::success_rates`
- [x] 5.2 Attempt distribution — `analysis/success.py::attempt_distribution`
- [x] 5.3 Attempt-over-attempt delta — convergence or resampling?
      — `analysis/success.py::convergence` (marginal success per attempt + verdict)
- [x] 5.4 **Failure taxonomy**, hand-classified: wrong-API / ManimGL-confusion /
      syntax / import / semantic — `analysis/taxonomy.py` (class vocabulary +
      traceback pre-classifier to seed the human pass; hand labels drive the counts.
      SEMANTIC is human-only by construction — the probe cannot see it)
- [x] 5.5 Throughput degradation curve vs concurrency
      — `analysis/throughput.py::throughput_curve`
- [x] 5.6 VRAM headroom under the longest grounded prompts
      — `analysis/throughput.py::vram_headroom`

## 6. Act on what you find

_All unchecked: acting requires real findings from a live run plus human judgement.
The **trigger logic is built** — `analysis/report.py::_section_advisories` computes
which branch the evidence points to and renders it as an advisory — but pulling any
of these levers is a deliberate human decision made against real data, so none can be
completed as scaffolding._

- [ ] 6.1 If failures are mostly ManimGL-confusion → the corpus is the lever;
      improve it and re-run. Cheap, and likely to move the number.
- [ ] 6.2 If failures are mostly semantic → grounding will not help. Record the
      ceiling honestly rather than tuning around it.
- [ ] 6.3 If repair shows no attempt-over-attempt improvement → the budget is
      buying nothing. Cut it to 1. Do not raise it hoping for a different result.
- [ ] 6.4 If MANIMA itself buckled under load → fix MANIMA. That is a real bug
      the harness earned its keep by finding.
