# MANIMA

Local-first MCP server that **renders** Manim Community Edition animations and,
optionally, **generates** the Manim source locally with Apertus 8B. Two tool surfaces,
neither privileged: `render_animation` (thin — the caller supplies source) and
`generate_animation` (thick — grounded local generation, probe-verified, bounded repair).

The product is the animation tool. It also happens to be a realistic workload for
exercising a local model under load — see [`harness/`](harness/).

## Deploy it (render-only, one command)

The render path is the sovereign surface: it needs only Docker — no GPU, no vLLM, no
Qdrant — and it never depends on the generator (invariant 6). That is the default
deployment. **Run inside WSL2** (the server side lives in WSL2; see
[`openspec/project.md`](openspec/project.md)).

```bash
cp .env.example .env      # defaults are render-only; edit if you like
make install              # pip install -e the server (render path)
make deploy               # build the pinned render image → verify Docker → smoke a render
```

`make deploy` finishes only if a trivial scene actually rendered — "started" is not
"healthy" (invariant 3). It then prints the exact line your MCP client uses to launch the
server:

```bash
MANIMA_RENDER_ONLY=1 python -m manima_server.server   # cwd: manima_server/
```

**Prefer not to build the ~9-minute TeX image locally?** Pull the published one instead:

```bash
make deploy-pull      # docker compose pulls ghcr.io/groscy/manima-render:pinned, then smokes it
```

`deploy-pull` sets `MANIMA_RENDER_IMAGE` to the GHCR ref — the same variable the server
reads — so the sandbox spawns containers from exactly what was pulled. (The image is
published on release tags; it must be public, or you must `docker login ghcr.io`, to pull it.)

`make help` lists every target. All configuration lives in one file, `.env`
(copied from [`.env.example`](.env.example)); the real `.env` is never committed.

## Turn on generation (opt-in)

The generate path needs a GPU, an external vLLM serving Apertus 8B, and Qdrant. It is
opt-in and never a prerequisite for render:

```bash
make generate-up          # starts Qdrant (vLLM stays external — point MANIMA_VLLM_URL at it)
python manima_server/scripts/build_corpus.py   # build the grounding corpus
```

Set `MANIMA_RENDER_ONLY=0` (and the generate knobs in `.env`) to wire it into the server.

## Deployment shapes and the sandbox boundary

Every render — generated or operator-supplied — executes inside a sandboxed container;
there is no host-execution path (invariants 1 & 5). The default deployment keeps the MCP
server **on the host**, where it spawns short-lived render containers. This preserves the
sandbox model exactly as designed.

> **Opt-in, not default:** you can instead run the server itself inside a container by
> mounting the host Docker socket so it can spawn sibling render containers
> (docker-out-of-docker). Be honest about the cost: **socket access is
> host-root-equivalent.** Use that shape only where that trade-off is acceptable; it is
> deliberately not the path `make deploy` takes.

Containment on WSL2 is the VM boundary first, container controls second — adequate for
careless or broken scenes, not a claim of hardened isolation. See `openspec/project.md`.

## Continuous integration

GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs on every push
and PR, all without a GPU:

- the offline test suites (`manima_server`'s 28 stdlib-only tests; the harness is compiled),
- `ruff` lint + `hadolint` on the render Dockerfile,
- `openspec validate --all --strict`,
- a render-image **build** check (cached); the image is **published to GHCR only on a
  release tag**, using the built-in token — no secret to configure.

**What CI does not run, and does not fake green:** the generate path's live behaviour
(Apertus/vLLM, Qdrant grounding, GPU-bound rendering). A GitHub-hosted runner has no GPU
and not the 16 GB VRAM it needs. That surface is verified on real hardware, not here.

## Layout

| Path | What |
|---|---|
| [`manima_server/`](manima_server/) | the MCP server — hexagonal core + adapters, the five tools, the render Dockerfile |
| [`harness/`](harness/) | the Apertus load-test harness — an ordinary client of the server |
| [`openspec/`](openspec/) | specs, conventions (`project.md`), and change proposals |
| `docker-compose.yml`, `Makefile`, `.env.example` | the deployment surface |

## Non-negotiables

Enforced structurally (`openspec/project.md`): all execution sandboxed; escalation
deny-by-default; no unverified success; artifacts referenced not embedded; static
validation is not the security boundary; `render_animation` never depends on the
generator.
