## Context

MANIMA today is: a Python package (`manima_server`), a sibling harness, a pinned
render-image `Dockerfile`, and `scripts/bringup.sh` — a five-step WSL2 sequence with
manual placeholders. The pure core is unit-tested (28 offline tests); the adapters are
written against real contracts but unverified because they need Docker/GPU/vLLM. There
is no compose file, no CI, no dependency lock, no health check, and no published remote.

Three constraints dominate every decision here:

1. **The server speaks MCP over stdio.** It is *launched by a client per session*, not
   run as a network daemon. "Deploy" therefore cannot mean `docker compose up` a
   long-lived server the way it would for an HTTP service — not without changing the
   transport, which is out of scope.
2. **The render path must stand alone (invariant 6).** It is the sovereign, portable
   surface. The generate path drags in GPU + vLLM + Qdrant and cannot be assumed on an
   arbitrary host or a CI runner.
3. **The sandbox is the security boundary (invariants 1 & 5).** Any deployment
   convenience that touches containment must be weighed against it, and any trade-off
   stated plainly — the project's own rule (`project.md`: "Say so plainly").

## Goals / Non-Goals

**Goals:**

- A second person can stand up a working `render_animation` on a Docker host with one
  command and no GPU.
- A push runs everything that *can* run without a GPU: the offline suites, lint, spec
  validation, and a render-image build check.
- The render image is publishable to a registry, gated to releases.
- The project is publishable to `github.com/groscy/manima` — on explicit human go-ahead.
- Every non-negotiable survives intact; every containment trade-off is documented.

**Non-Goals:**

- Changing the MCP transport (no HTTP/SSE server). The stdio contract is unchanged.
- Running the generate path (Apertus/vLLM/Qdrant/GPU) in CI. It is declared uncovered,
  not stubbed green.
- Hardening WSL2 containment beyond what `project.md` already documents.
- Multi-arch images. `linux/amd64` only unless a need appears.
- Any change to `core/`, `adapters/`, `server.py`, or the Dockerfile's *contents*.

## Decisions

### D1 — Default deployment keeps the server on the host; compose provisions the pieces

Because the server is stdio-launched, the default deployment does **not** run the
server as a container. Instead:

- `docker compose build` produces the pinned `manima-render:pinned` image (build-arg
  fed from `version.py`).
- `docker compose --profile generate up -d` provisions the generate-path services
  MANIMA *owns* (Qdrant). vLLM stays external — it is GPU-bound and deployment-specific,
  exactly as `bringup.sh` already treats it.
- A single `Makefile`/`deploy.sh` entrypoint orders it: build image → verify Docker
  reachable → (optional) start services → print the exact `python -m manima_server.server`
  line the MCP client invokes → run the smoke test.

*Alternative considered — containerize the server with a Docker-socket mount
(docker-out-of-docker) and expose HTTP MCP.* Rejected as the default: it requires a
transport change (out of scope) and mounting `/var/run/docker.sock` is root-equivalent
on the host, which weakens the very boundary invariants 1/5 protect. It is offered as a
**documented opt-in** (D4), not the path of least resistance.

### D2 — Render-only is the default; generate is a compose profile

The entrypoint defaults to `MANIMA_RENDER_ONLY=1`. The generate path is a named
`generate` profile the operator turns on. This makes invariant 6 structural in the
deployment, not just the code: the thing you get by default imports no generate
dependency and needs no GPU. Matches the existing `MANIMA_RENDER_ONLY` switch in
`config.py` — no new mechanism, just wired into deployment.

### D3 — One env file is the single source of operator config

A committed `.env.example` enumerates every `MANIMA_*` knob (`config.py`), endpoints,
TTLs, sandbox limits, and the render-only flag, with safe defaults and no real secrets.
The real `.env` is git-ignored. Compose and the entrypoint read from it. Rationale: the
current knobs are scattered across `config.py` and `bringup.sh` env expansions;
operators need one place to look.

### D4 — The socket-mount server container is opt-in and documented, never default

For operators who genuinely want a containerized server (e.g. HTTP-MCP clients), the
deployment docs describe the docker-socket shape and state the trade-off in one
sentence: *the server container gains host-root-equivalent access via the socket; use
it only where that is acceptable.* This satisfies the `deployment` spec's
"trade-off documented" requirement without making it the default anyone lands on.

### D5 — CI: four jobs on `ubuntu-latest`, all GPU-free

- **test** — matrix `{manima_server, harness}`, Python 3.12, `pip install -e .[dev]`,
  `pytest`. Stdlib-only offline suites; runs anywhere.
- **lint** — `ruff` over both packages (added as a dev-only dependency), plus
  `hadolint` on the render Dockerfile (cheap, no build).
- **spec-validate** — Node + `openspec validate --strict` so malformed specs/changes
  fail the pipeline.
- **render-image** — `docker/build-push-action` with buildx + GHA layer cache; the
  Manim CE version is read from `version.py` and passed as the build-arg. Builds on
  push/PR (cached), **pushes to GHCR only on a release tag**, authenticated with the
  built-in `GITHUB_TOKEN` (no operator secret needed).

*Alternative — build the full image on every PR without caching.* Rejected: the
`texlive-full` layer is multi-gigabyte; an uncached build is 20–40 min and heavy
bandwidth. Layer caching makes the texlive layer a one-time cost; subsequent builds are
fast. Cache-cold first run is accepted and noted (R1).

### D6 — Version pin flows from `version.py` into CI and the image

Both the deployment entrypoint and the CI build-arg derive `MANIM_CE_VERSION` from
`manima_server.version` — never hard-coded a second time. Upholds the convention that
the pinned version lives in exactly one place and flows outward.

### D7 — Dependency locks for reproducibility

`pip-tools` generates a locked constraints file per package from `pyproject.toml`. CI
and deployment install against the lock so a fresh environment resolves to the same
versions the tests passed on. Kept minimal — locks are additive, not a packaging
rewrite.

### D8 — Publication is a human-gated, one-time Git action, never a workflow

Adding the `github.com/groscy/manima` remote and pushing `main` is done by a person on
explicit confirmation, in the implementation phase. **No `.github/workflows` file ever
pushes project source.** The registry publish (D5) pushes an *image artifact* on a tag;
it never pushes the repository. This keeps the outward-facing, public action under
direct human control (per the safety boundary on publishing public content).

## Risks / Trade-offs

- **[texlive-full build cost in CI]** → buildx + GHA layer cache; the giant layer is
  cached after the first run. Publish-heavy full builds are gated to tags. First
  cache-cold build is slow and that is accepted and documented.
- **[Docker-socket server container is root-equivalent]** → not the default (D1/D4);
  offered only as a documented opt-in with the trade-off stated. Default keeps the
  server on the host and the sandbox model intact.
- **[Green CI ≠ generate path works]** → the pipeline explicitly declares the
  generate/GPU surface as uncovered (ci-pipeline spec) rather than faking it. A
  reader is never misled that a green check verified Apertus.
- **[`.env.example` leaking a real secret]** → the committed file carries placeholders
  only; the real `.env` is git-ignored; CI needs no MANIMA secret (GHCR uses the
  built-in token).
- **[Public remote may not exist / auth may fail at push time]** → precondition, not a
  blocker for the rest: the deployment and CI land independently of publication;
  publication is the last, human-run step.
- **["Deployed" overclaimed]** → the smoke test is the gate (invariant 3 applied to
  deployment): no green without a scene actually rendering.

## Migration Plan

Additive and reversible. Nothing in `core/`, `adapters/`, or `server.py` changes.

1. Land lockfiles, `.env.example`, `docker-compose.yml`, and the `Makefile`/`deploy.sh`
   entrypoint (render-only default). Verify the smoke test renders a scene.
2. Land the `.github/workflows` (test, lint, spec-validate, render-image build). Confirm
   green on a PR.
3. Update `bringup.sh` and both READMEs to point at the one-command flow.
4. **On explicit confirmation only:** add the `origin` remote at
   `github.com/groscy/manima` and push `main`; enable the tag-gated GHCR publish.

**Rollback:** delete the new deployment files and workflows; the server and its tests
are untouched, so there is nothing to revert in the product itself. The default
deployment is render-only, so no behavioural regression is possible from this change.

## Open Questions

- **HTTP-MCP server container** — is a containerized, network-transport server wanted
  now, or deferred? D1/D4 defer it (stdio unchanged) and document the socket trade-off;
  revisit if a client needs HTTP transport.
- **Does `github.com/groscy/manima` already exist and is it empty?** Publication (D8)
  assumes an empty remote to push into; if it has history, the push strategy needs a
  human decision before step 4.
