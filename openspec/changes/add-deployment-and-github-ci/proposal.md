## Why

MANIMA is built and unit-tested, but there is no way to *deploy* it that a second
person could follow without reverse-engineering `bringup.sh`, and no automation
guarding the code against regression. Bring-up is a manual, five-step WSL2 ritual
with placeholders ("start your vLLM process here"), no pinned dependency lock, no
health check, and no single entrypoint. Nothing runs the 28-test offline suite on
push. And the work lives only on this machine — there is no published remote at
`github.com/groscy/manima`.

This change makes MANIMA *deployable by someone who is not its author* and puts a
pipeline in front of it, without compromising a single non-negotiable.

## What Changes

- **A one-command, render-only deployment.** The sovereign path — `render_animation`
  with `MANIMA_RENDER_ONLY=1` — is the one that runs on any machine with Docker. It
  becomes the default deployment: build the pinned render image, start the server,
  render a smoke scene, done. No GPU, no vLLM, no Qdrant required. This honours
  invariant 6 (render never depends on the generator) by making render the thing you
  can actually stand up alone.
- **The generate path as an explicit opt-in overlay**, not the default. It carries
  GPU/vLLM/Qdrant requirements that cannot be assumed on a CI runner or an arbitrary
  host, so it is a documented profile you turn *on*, never a dependency you must
  satisfy to get render working.
- **`docker compose` + a `Makefile`/`deploy` entrypoint** wrapping the ordered
  bring-up, with a render-only default target and a `generate` profile. Config moves
  to a single `.env.example` enumerating every `MANIMA_*` knob.
- **A deployment smoke test**: render a trivial scene end to end and assert
  `SUCCEEDED`. "Deployed" means a scene actually rendered — the same honesty bar as
  invariant 3, applied to deployment.
- **GitHub Actions CI**: run the stdlib-only offline suite for `manima_server` and
  `harness`, lint, and `openspec validate --strict` on every push and PR. This is the
  part that runs *anywhere* — no GPU, no Docker daemon needed for the core.
- **A render-image build job** that proves the pinned Dockerfile still builds, and
  (on tags only) publishes it to GHCR. Buildability is verified on every relevant
  change; publication is gated to releases.
- **Honest CI boundaries, documented.** GitHub-hosted runners have no GPU and no
  16 GB VRAM. The generate path's live behaviour (Apertus, grounding) is
  *unrunnable* in CI and is declared so, not faked green.
- **Publication to `github.com/groscy/manima`** as the origin remote — an outward,
  public action, performed only on explicit confirmation, never automatically.

## Capabilities

### New Capabilities

- `deployment`: How MANIMA is stood up by someone other than its author — the
  render-only default, the opt-in generate profile, single-file env config, a
  one-command entrypoint, and a deployment smoke test that proves a scene rendered.
- `ci-pipeline`: The GitHub automation — offline test + lint + spec-validation on
  push/PR, render-image build verification, gated image publication, and the
  honestly-drawn line around what cannot run on a GPU-less runner.

### Modified Capabilities

<!-- None. render, generate, jobs, and sandbox behaviour is unchanged at the spec
     level; this change adds how the system is packaged and guarded, not what the
     tools do. -->

## Impact

- **New files (implementation, out of OpenSpec scope):** top-level `docker-compose.yml`,
  `Makefile` (or `deploy.sh`), `.env.example`, `.github/workflows/*.yml`, a deployment
  smoke test, and dependency lockfiles for `manima_server` and `harness`.
- **Existing code:** `scripts/bringup.sh` and both `README.md`s are updated to point at
  the new one-command flow; `config.py`'s env knobs are surfaced in `.env.example`. No
  change to `core/`, `adapters/`, `server.py`, or the render Dockerfile's contents.
- **Dependencies:** no new runtime dependency for the render path. CI adds dev-only
  tooling (a linter, the existing `pytest`). GHCR publication needs no new secret — the
  built-in `GITHUB_TOKEN` covers it.
- **External surface:** a new public Git remote at `github.com/groscy/manima`, and
  (on tags) a published render image at `ghcr.io/groscy/manima-render`. Both are
  outward-facing and performed only with explicit user confirmation.
- **Non-negotiables:** all six hold. The sandbox is not weakened; if the deployment
  containerizes the server itself, the Docker-socket trade-off is documented honestly
  rather than papered over (see design.md).
