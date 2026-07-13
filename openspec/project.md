# MANIMA — Project Conventions

## Purpose

Local-first MCP server that renders Manim Community Edition animations, and
optionally generates the Manim source locally using Apertus 8B.

**The product is the animation tool.** MANIMA also happens to be a realistic
workload for exercising Apertus under load — but that testing happens *around*
the application, not inside it. No design decision here is made to serve the
benchmark at the animation tool's expense.

Two tool surfaces, deliberately:

- `render_animation` — thin path. The caller supplies Manim source.
- `generate_animation` — thick path. Apertus 8B generates it here, locally.

Neither is privileged. The caller chooses, per call, whether to trade generation
quality for sovereignty.

## Non-negotiables

Architectural invariants. A change that violates one is rejected regardless of
what it buys.

1. **All execution is sandboxed.** Including operator-supplied source. There is
   no trusted-source fast path. (ADR-001)
2. **Escalation is deny-by-default.** Three independent gates — server config,
   per-call flag, exhausted local budget — must *all* be satisfied. (ADR-003)
3. **No unverified source is reported as successful.** `SUCCEEDED` means the
   scene actually rendered. (ADR-003)
4. **Artifacts are referenced, never embedded.** (ADR-004)
5. **Static validation is not a security boundary.** The sandbox is. Never
   weaken the sandbox on the grounds that the validator is present.
6. **`render_animation` never depends on the generator.** The animation tool must
   remain fully functional if generation turns out to be unusable.

## Stack

| Concern | Choice |
|---|---|
| Host | Windows 11 desktop, NVIDIA GPU, 16 GB VRAM |
| Server | Python 3.12, `mcp` SDK, stdio transport — **in WSL2** |
| Inference | Apertus 8B (int4) on **vLLM** — in WSL2, OpenAI-compatible endpoint |
| Grounding | Qdrant, corpus built from the pinned Manim CE version |
| Sandbox | Docker Desktop (WSL2 backend), one container per render |
| Render image | Manim CE (pinned) + full TeX Live |
| Store | Content-addressed, **inside the WSL2 filesystem** |

### Why 8B

16 GB VRAM. Apertus 8B at int4 is ~6 GB, leaving headroom for the KV cache of a
long grounded prompt. Apertus 70B is ~40 GB at Q4 and does not fit. This is
arithmetic, not preference.

Be honest about what that means: an 8B model writing correct Manim CE is a hard
ask. Small models lean on the dominant training-data pattern, and for Manim that
pattern is ManimGL and older CE versions — the wrong answer. Grounding and the
repair loop are not polish; they are the reason this path might work at all.

### Why not Colibri

Investigated and rejected. Colibri is a disk-streaming engine purpose-built for
GLM-5.2 (744B MoE), not a general runtime. It runs at roughly 0.1-1 tok/s, which
is incompatible with a repair loop needing several generations per animation.
Wrong tool for this workload.

## Platform notes (Windows)

- vLLM on Windows is WSL2-only. Docker Linux containers need WSL2. So the whole
  server side lives in WSL2; only the MCP client is Windows-native.
- **Keep the artifact store inside the WSL2 filesystem.** Cross-boundary I/O to
  `/mnt/c` is slow enough to matter for multi-megabyte video.
- **Sandbox containment on WSL2 is weaker than Linux-native rootless Docker.**
  The WSL2 VM boundary is the primary containment; container controls are defence
  in depth inside it. Adequate for careless or broken code — not a claim of
  hardened isolation. Say so plainly rather than implying otherwise.

## Conventions

- Ports in `core/ports/`, adapters in `adapters/`. The core imports no adapter.
- Every job carries a structured trace: generator identity, attempt count,
  validation verdicts, tracebacks, escalation flag.
- The Manim CE version is pinned in one place and flows into: the render image,
  the grounding corpus, and the artifact hash. Bumping it means rebuilding all
  three, in that order.

## Currency

CHF. Escalation receipts record token counts and cost.
