# Generate

## Purpose

The thick path. Turn a natural-language prompt into a *verified* Manim CE scene,
using a local model, without the prompt or source leaving the workstation.

The word doing the work here is **verified**. A generator alone is not enough:
Manim CE's API is version-sensitive and heavily confusable with ManimGL, and a
local model will confidently emit code that does not run. This capability exists
to convert that unreliable generator into a component with an honest output
contract.

## Requirements

### Requirement: The system SHALL expose a `generate_animation` tool

The system SHALL expose an MCP tool `generate_animation` that turns a natural-language
prompt into a probe-verified Manim CE scene using the local generator.

Arguments: `prompt` (required), `quality` (optional), `repair_budget` (optional,
default 3), `allow_escalation` (optional, default false).

Returns: `job_id`, immediately.

#### Scenario: Prompt produces a rendering scene

- **WHEN** `generate_animation` is called with a prompt
- **THEN** a `job_id` is returned within 2 seconds
- **AND** on success `job_result` returns the artifact path, the final source,
  and the full attempt trace

### Requirement: Generation SHALL be grounded in a pinned Manim CE corpus

Before each generation attempt, the system SHALL retrieve top-k API snippets for
the pinned Manim CE version from Qdrant and inject them into the prompt.

#### Scenario: Grounding pins the API version

- **WHEN** a prompt would plausibly elicit a ManimGL construct such as
  `ShowCreation`
- **THEN** the retrieved grounding contains the Manim CE equivalent
- **AND** the corpus is built from the exact Manim CE version present in the
  render image

### Requirement: Candidate source SHALL be probe-rendered before acceptance

Every candidate SHALL be rendered at 240p, single frame, in the sandbox, purely
as a correctness oracle. Only probe-verified source proceeds to full quality.

#### Scenario: Probe catches an API error

- **WHEN** the generator emits a call that does not exist in the pinned Manim CE
- **THEN** the probe render raises
- **AND** the traceback is captured as repair context

#### Scenario: Probe is a syntax and API oracle only

- **WHEN** a scene passes the probe but has incorrect animation timing
- **THEN** the job still succeeds
- **AND** the system does not claim semantic validation — `job_result` reports
  what was verified, which is that the scene runs, not that it is correct

### Requirement: Failed candidates SHALL be repaired within a bounded budget

On probe failure or validation rejection, the source and the error SHALL be fed
back to the generator as repair context. Attempts SHALL be bounded by
`repair_budget`.

#### Scenario: Repair converges

- **WHEN** attempt 1 fails on a traceback
- **THEN** attempt 2 receives the source and the traceback
- **AND** the traceback names the exact construct that failed

#### Scenario: Budget exhausted, escalation closed

- **WHEN** all attempts fail and `allow_escalation` is false
- **THEN** the job transitions to `FAILED`
- **AND** `job_result` returns the last traceback and the best-effort source,
  so the caller — who is very likely a stronger model — can take it from there

#### Scenario: Repair is measurably useless

- **WHEN** attempt-over-attempt success shows no improvement across the benchmark
- **THEN** the budget is buying nothing and SHALL be reduced
- **AND** this SHALL be treated as a finding about the generator, not a tuning
  parameter to be raised

### Requirement: Escalation SHALL be deny-by-default

Escalation to a hosted model SHALL require *all three*: server config permits it,
the call passes `allow_escalation: true`, and the local repair budget is exhausted.

#### Scenario: Air-gapped operation

- **WHEN** the host network is disabled entirely and the gate is closed
- **THEN** `generate_animation` completes successfully
- **AND** no egress is attempted — confirming the sovereignty property by
  observation rather than by assurance

#### Scenario: Escalation emits a receipt

- **WHEN** escalation fires
- **THEN** a receipt records job id, model called, token counts, and the reason
  the local path failed

### Requirement: The generator SHALL sit behind a port

`AnimationGenerator` SHALL be a port. Apertus 8B served by vLLM is one adapter;
the escalation model is another.

#### Scenario: Generator is swapped

- **WHEN** the local generator is replaced with a different model
- **THEN** no change to the core, the repair loop, or the tool surface is required

#### Scenario: Local generator proves inadequate

- **WHEN** benchmark results show the local generator cannot clear a usable bar
- **THEN** `render_animation` remains fully functional as the primary path
- **AND** the architecture degrades gracefully rather than failing entirely
