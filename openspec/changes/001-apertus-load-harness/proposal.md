# 001 — Apertus Load-Test Harness

## Status

Proposed. Sits **outside** MANIMA and drives it through the public MCP surface.

## What changed from the original framing

This was first drafted as a go/no-go gate: measure Apertus, and only build the
generator if it cleared a bar. That was the wrong shape.

MANIMA is an animation tool. It should be built as one and judged as one. Apertus
load-testing is a *use* of that tool — a demanding, repeatable workload that
happens to exercise a local model hard — not a gate standing in front of it.

This matters practically. A benchmark welded into the product makes a worse
product and a worse benchmark. Keeping them separate means the animation tool is
judged on whether it produces animations, and the load test is free to hammer it
in ways no ordinary user would.

## Why Manim is a good load test

Worth stating explicitly, because it is why this pairing works at all.

**The oracle is mechanical.** The scene renders or it does not. No LLM-as-judge,
no rubric, no scoring model, no vibes. A traceback is ground truth. That is a rare
property in LLM evaluation and it should be exploited, not diluted.

**The task is adversarially hard for a small model.** Manim CE's API has drifted,
and ManimGL forms dominate the training distribution. An 8B model reaches for the
statistically likely answer, which here is frequently the wrong one. A real
stressor, not a toy.

**The load profile has natural shape.** Generation is bursty and long-prompted
(grounding injection); the repair loop creates dependent sequential calls; a queue
of animations creates sustained concurrent pressure. More interesting than a
synthetic token-throughput benchmark.

## What this change adds

A harness, external to the server, driving MANIMA's MCP surface under load.

### Workload profiles

| Profile | Shape | Stresses |
|---|---|---|
| Soak | One prompt at a time, sustained for hours | Memory stability, KV cache growth, thermals |
| Burst | N concurrent `generate_animation` calls | vLLM queueing, job manager, container pressure |
| Repair-heavy | Prompts chosen to reliably fail first-pass | The repair loop at its worst case |
| Mixed | `render_animation` and `generate_animation` interleaved | Contention between the two paths |

### Prompt suite

Graded, reused across all profiles. Minimum 10 per tier.

- **Easy** — plot a function, render an equation, basic mobjects
- **Medium** — transforms, updaters, multi-stage choreography
- **Hard** — 3D scenes, camera movement, matrix operations

### What gets measured

**On Apertus** — the point of the exercise:

- Tokens/sec per profile; degradation as concurrency rises
- VRAM headroom with a long grounded prompt. 16 GB is not much, and grounding
  injection makes the prompt long precisely when the KV cache is largest
- First-pass and post-repair success rates, per tier
- Attempt-over-attempt delta — does repair *converge*, or merely resample?
- **Failure taxonomy**: wrong-API / ManimGL-confusion / syntax / import /
  semantic. Hand-classified. The highest-value output by some margin.

**On MANIMA** — does the tool hold up:

- Tool-call latency stays under 2 s regardless of load
- Job state machine survives burst and mid-render cancellation
- No container leaks under sustained pressure
- Content-addressed cache behaves under concurrent identical requests

### The control condition

Run the same suite against a frontier model via `render_animation`.

Without it an Apertus number is uninterpretable. If Apertus scores 45% and a
frontier model scores 95%, that is a model-capability finding. If the frontier
model also scores 60%, the problem is the grounding corpus or the prompt template,
and no amount of model-swapping fixes it. **Do not skip this.**

## What the results mean

Deliberately *not* a pass/fail gate — nothing downstream depends on it:

- **Apertus does well** → `generate_animation` is a genuinely useful local path.
- **Apertus does poorly** → a *finding*, not a failure. `render_animation` is
  unaffected and remains fully functional. The `AnimationGenerator` port means a
  better model drops in later with no change to the core.

The taxonomy is more informative than the headline rate either way. If failures
are dominated by ManimGL-confusion and wrong-API, the grounding corpus is the
lever and may improve sharply. If failures are semantic — the model does not
understand the mathematics it is being asked to animate — grounding will not help
and the ceiling is the model's own.

## Scope

- **In:** harness, workload profiles, prompt suite, frontier control, metrics,
  failure taxonomy, report.
- **Out:** MANIMA itself. The harness is an ordinary client. No privileged access,
  no special endpoints, no hooks into server internals. If driving it under load
  requires something the MCP surface does not expose, that is a finding about the
  surface — record it rather than reaching around it.

## Affected specs

None. This consumes the public tool surface exactly as any client would.

## Depends On

_None open. Depended on `build-manima-server`, which was implemented and archived on
2026-07-13; this change is now unblocked._
