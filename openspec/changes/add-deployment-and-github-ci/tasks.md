# Tasks — add-deployment-and-github-ci

**Sequencing.** Deployment and CI are independent and can land in either order;
publication to the public remote is deliberately last and human-gated (design D8).
Nothing here touches `core/`, `adapters/`, `server.py`, or the Dockerfile's contents.

**Status legend.** `[x]` = implemented and inspectable in this environment. Items that
need a **Docker host**, **network + pip-tools**, or a **live CI/PR run** to *observe* are
authored but marked `[ ]` with a note — the same honesty bar the repo already applies
(no faking a green a GPU-less/Dockerless box cannot produce). Windows dev box here: no
Docker, no ruff, no pip-tools, no GPU.

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
- [ ] 2.2 Generate a locked constraints file per package from `pyproject.toml`
      — **mechanism in place** (`make lock` runs `pip-compile --extra dev`); the actual
      resolution needs pip-tools + network, absent here, so the lock files are not yet
      committed. Run `make lock` on a connected box to produce them.
- [ ] 2.3 Confirm a clean `pip install` against the lock reproduces a passing offline
      run — blocked on 2.2 (no lock to install against here)

## 3. Compose + one-command deployment (design D1–D2)

- [x] 3.1 Add a root `docker-compose.yml` with a build target producing
      `manima-render:pinned`, `MANIM_CE_VERSION` sourced from `version.py` via `make` (D6)
- [x] 3.2 Add a `generate` compose profile that provisions Qdrant (vLLM stays external)
- [x] 3.3 Add the entrypoint (`Makefile`) ordering: build image → verify Docker →
      print the exact `python -m manima_server.server` launch line → run the smoke test
- [x] 3.4 Default the entrypoint to render-only (`MANIMA_RENDER_ONLY=1`); generate is
      opt-in only (`make generate-up`)
- [ ] 3.5 Verify render-only stands up on a Docker host with no GPU/vLLM/Qdrant and
      imports no generate-path dependency — **run-blocked: needs a Docker host.** The
      wiring guarantees it (server gates the generate imports on `MANIMA_RENDER_ONLY`; the
      Makefile/smoke force it to `1`); `make deploy` confirms it on real infra.

## 4. Deployment smoke test (deployment spec, invariant 3)

- [x] 4.1 Smoke test submitting a trivial scene via `render_animation`, polling to
      terminal, asserting `SUCCEEDED` + a retrievable `job_result` artifact
      — `manima_server/scripts/smoke_render.py` (syntax-checked; live run is Docker-gated)
- [x] 4.2 Fail loudly (non-zero) when the sandbox is misconfigured — the script's
      top-level `except` turns a server that won't start (Docker unreachable →
      `SandboxUnavailable` at preflight → failed stdio init) into exit 1

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
- [ ] 6.6 Confirm the pipeline goes green on a trial PR and red when a test is broken
      — **needs a live CI run** (pushed to GitHub); cannot be observed from this box.
      Ties into task 9 (publication) — the first PR after publish is the confirmation.

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
