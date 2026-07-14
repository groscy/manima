# Tasks — add-deployment-and-github-ci

**Sequencing.** Deployment and CI are independent and can land in either order;
publication to the public remote is deliberately last and human-gated (design D8).
Nothing here touches `core/`, `adapters/`, `server.py`, or the Dockerfile's contents.

**Status legend.** `[x]` = implemented and inspectable in this environment. Items that
need a **Docker host** or a **live CI/PR run** to *observe* are authored but marked `[ ]`
with a note — the same honesty bar the repo already applies (no faking a green a
GPU-less/Dockerless box cannot produce). The Windows dev box has no Docker/ruff/GPU; the
dependency locks (2.2) and the clean-install offline-suite verification (2.3) were
produced in **WSL Ubuntu (Linux, Python 3.12.3 — the CI runner's platform)** via a
bootstrapped pip-tools. What still needs a **Docker daemon** (3.5 render half) or an
**outward push** (6.6 red half) remains `[ ]`.

## 1. Configuration surface

- [x] 1.1 Enumerate every `MANIMA_*` knob read by `manima_server/manima_server/config.py`
      (endpoints, TTLs, sandbox limits, `MANIMA_RENDER_ONLY`) with its default
      — captured in `.env.example`, split into server-read vs deployment/compose knobs
- [x] 1.2 Write a committed `.env.example` at repo root with those knobs, safe
      defaults, and placeholder-only secrets (deployment spec: single env file)
- [x] 1.3 Ensure the real `.env` is git-ignored (extend root `.gitignore`)

## 2. Dependency locks (design D7)

- [x] 2.1 Add `ruff` and `pip-tools` to the `[dev]` extra of both
      `manima_server/pyproject.toml` and `harness/pyproject.toml` (harness gained a `[dev]`)
- [x] 2.2 Generate a locked constraints file per package from `pyproject.toml`
      — generated on **Linux + Python 3.12.3** (matching the CI runner, via pip-tools
      7.5.3) so the pins carry no Windows-only leakage; committed at
      `manima_server/requirements.lock` and `harness/requirements.lock`. Reproduce with
      `make lock` on any connected Linux box.
- [x] 2.3 Confirm a clean `pip install` against the lock reproduces a passing offline
      run — fresh venv, `pip install -r requirements.lock` then `-e . --no-deps`:
      `manima_server` offline suite is **28 passed**; `harness` installs and compiles
      clean (empty suite tolerated, as CI does).

## 3. Compose + one-command deployment (design D1–D2)

- [x] 3.1 Add a root `docker-compose.yml` with a build target producing
      `manima-render:pinned`, `MANIM_CE_VERSION` sourced from `version.py` via `make` (D6)
- [x] 3.2 Add a `generate` compose profile that provisions Qdrant (vLLM stays external)
- [x] 3.3 Add the entrypoint (`Makefile`) ordering: build image → verify Docker →
      print the exact `python -m manima_server.server` launch line → run the smoke test
- [x] 3.4 Default the entrypoint to render-only (`MANIMA_RENDER_ONLY=1`); generate is
      opt-in only (`make generate-up`)
- [x] 3.5 Verify render-only stands up on a Docker host with no GPU/vLLM/Qdrant and
      imports no generate-path dependency — **VERIFIED live, both halves.** (a) Import
      isolation: in a base-only venv (`pip install -e manima_server`, no extras)
      `openai`/`qdrant_client`/`anthropic`/`fastembed` are all absent, and
      `MANIMA_RENDER_ONLY=1 python -c "import manima_server.server"` loads the server with
      **zero** generate modules in `sys.modules` and `_generate_configured() is False`.
      (b) Real render: built `manima-render:pinned` (5.29 GB, Manim CE 0.18.1 + full TeX
      Live) and ran `smoke_render.py` under rootless **podman** (`MANIMA_CONTAINER_CLI=podman`,
      cgroup-v2 limits enforced) with no GPU/vLLM/Qdrant — job SUCCEEDED with a retrievable
      4344-byte MP4 artifact in the content-addressed store.

## 4. Deployment smoke test (deployment spec, invariant 3)

- [x] 4.1 Smoke test submitting a trivial scene via `render_animation`, polling to
      terminal, asserting `SUCCEEDED` + a retrievable `job_result` artifact
      — `manima_server/scripts/smoke_render.py`, now **run live** (rootless podman): the
      Circle scene reached SUCCEEDED with a retrievable 4344-byte MP4, exit 0.
- [x] 4.2 Fail loudly (non-zero) when the sandbox is misconfigured — the script's
      top-level `except` turns a server that won't start (container CLI unreachable →
      `SandboxUnavailable` at preflight → failed stdio init) into exit 1. **Confirmed
      live:** pointing it at an absent CLI (`MANIMA_CONTAINER_CLI=docker`, not installed)
      printed `SMOKE FAIL` and exited 1 without reporting healthy.

## 5. Document the containment trade-off (design D4, deployment spec)

- [x] 5.1 Document the opt-in containerized-server (Docker-socket) shape and state
      plainly that it is host-root-equivalent; keep it non-default — root `README.md`
      ("Deployment shapes and the sandbox boundary")
- [x] 5.2 Confirm no default deployment shape introduces a host-execution path for
      render — the default keeps the server on the host spawning sandboxed containers;
      no deploy artifact adds a host-exec path (invariants 1 & 5)

## 6. GitHub Actions CI (design D5, ci-pipeline spec)

- [x] 6.1 `test` workflow: matrix `{manima_server, harness}`, Python 3.12,
      `pip install -e .[dev]`, compile + `pytest` (tolerates the harness's empty suite)
- [x] 6.2 `lint` workflow: `ruff` over both packages + `hadolint` on the render
      Dockerfile (with `.hadolint.yaml` ignoring the two inapplicable full-TeX rules)
- [x] 6.3 `spec-validate` workflow: Node + `openspec validate --specs --strict` (the
      durable contract; delta-less in-flight changes are a pre-merge concern — see note ▼)
- [x] 6.4 `render-image` job: buildx + GHA layer cache, `MANIM_CE_VERSION` from
      `version.py`; builds on push/PR, does not push
- [x] 6.5 Declare the generate/GPU surface as out of CI scope — not faked green — in
      both the workflow header and the READMEs
- [x] 6.6 Confirm the pipeline goes green on a trial PR and red when a test is broken
      — **green CONFIRMED live; red demonstration explicitly waived.** The `CI` workflow
      has gone green on `master` pushes repeatedly, most recently the full 5-job run on
      commit `4374962` (test ×2, lint, spec-validate, render-image all success). The
      "red when a test is broken" half is structurally guaranteed by the `test` job
      (`python -m pytest … || code=$?` then `exit "$code"` for any non-5 code); the user
      decided a deliberately-broken PR on the public repo is not needed, so this half is
      closed as waived rather than observed — not faked green (the mechanism is inspectable
      in `.github/workflows/ci.yml`).

## 7. Gated render-image publication (ci-pipeline spec)

- [x] 7.1 `render-image` pushes to `ghcr.io/groscy/manima-render` **only on a release
      tag**, authenticated with the built-in `GITHUB_TOKEN` (no operator secret)
- [x] 7.2 A non-tag push/PR builds but does not publish — guaranteed by
      `push: ${{ startsWith(github.ref, 'refs/tags/') }}` and the tag-guarded GHCR login;
      inspectable now, run-confirmed by CI

## 8. Wire existing docs to the new flow

- [x] 8.1 `manima_server/scripts/bringup.sh` references the one-command `make` entrypoint
- [x] 8.2 `manima_server/README.md` and `harness/README.md` (and a new root `README.md`)
      carry the deploy + CI story and the CI-coverage boundary

## 9. Publish to the remote — human-gated, last (design D8, ci-pipeline spec)

- [x] 9.1 Confirm with the user that `github.com/groscy/manima` exists, is empty, and
      that they authorize publishing — **user authorized publishing to main.** Repo state:
      does **not exist yet** on GitHub, so the push is held until the user creates it.
- [x] 9.2 On explicit confirmation only: add `origin =
      https://github.com/groscy/manima.git` and push `main` — **done:** user created the
      repo and authorized the push; `git push -u origin main` landed, `main` tracks
      `origin/main`.
- [x] 9.3 Verify no workflow pushes project source automatically — confirmed: `git push`
      appears nowhere in `.github/`; only the tag-gated image publish sends an artifact
      outward
