## ADDED Requirements

### Requirement: CI SHALL run the offline test suite on every push and pull request

On every push and pull request, CI SHALL run the stdlib-only offline test suites for
both `manima_server` and `harness` on a GitHub-hosted runner, requiring no GPU, no
Docker daemon, and no external service. A failing test SHALL fail the pipeline.

#### Scenario: Offline suite passes

- **WHEN** a push or pull request triggers CI
- **THEN** the `manima_server` and `harness` offline test suites run to completion
- **AND** the job succeeds only if every test passes

#### Scenario: A regression is introduced

- **WHEN** a change breaks a test in the offline suite
- **THEN** the pipeline SHALL report failure
- **AND** SHALL block the pull request from a green status

### Requirement: CI SHALL lint and strict-validate the spec contract

CI SHALL run a linter over the Python sources and SHALL run `openspec validate --specs
--strict` so that a malformed spec fails the pipeline. The durable spec contract is the
CI gate; in-flight changes are validated by the author pre-merge (some legitimately carry
no spec delta, so change-level `--all` validation is not the pipeline gate).

#### Scenario: Spec validation on a malformed spec

- **WHEN** a committed spec fails `openspec validate --specs --strict`
- **THEN** the pipeline SHALL fail
- **AND** SHALL name the offending spec

#### Scenario: Lint violation

- **WHEN** the linter finds a violation in the Python sources
- **THEN** the lint job SHALL fail

### Requirement: CI SHALL verify the render image builds

CI SHALL build the pinned render image from `manima_server/docker/Dockerfile` to
prove it still builds, using the Manim CE version pinned in `version.py`. The build
SHALL run on push and pull request that could affect it.

#### Scenario: Render image builds

- **WHEN** CI runs the render-image build job
- **THEN** the image builds successfully from the pinned Dockerfile
- **AND** the pinned Manim CE version is the one used for the build

#### Scenario: A change breaks the render image

- **WHEN** a change makes the render Dockerfile fail to build
- **THEN** the build job SHALL fail the pipeline

### Requirement: Render-image publication SHALL be gated to releases

The render image SHALL be published to a container registry only on a release tag,
never on an ordinary push or pull request. Publication SHALL authenticate with the
built-in workflow token and SHALL NOT require an operator to add a registry secret.

#### Scenario: Publication on a release tag

- **WHEN** a release tag is pushed
- **THEN** CI publishes the render image to the container registry
- **AND** authenticates using the built-in workflow token

#### Scenario: No publication on an ordinary push

- **WHEN** a non-tag push or a pull request runs CI
- **THEN** the render image SHALL be built but SHALL NOT be published

### Requirement: CI SHALL declare what it cannot run

The pipeline SHALL NOT execute the generate path's live behaviour (Apertus/vLLM,
Qdrant grounding, GPU-bound rendering), because a GitHub-hosted runner has neither a
GPU nor the required VRAM. What CI does not cover SHALL be declared in the workflow
and in documentation rather than stubbed to a false green.

#### Scenario: Generate-path behaviour is not faked

- **WHEN** the pipeline runs
- **THEN** it SHALL NOT claim to have verified live Apertus generation or grounding
- **AND** the uncovered surface SHALL be documented as out of CI scope

### Requirement: The repository SHALL be publishable to the configured remote

The project SHALL be publishable to the remote `github.com/groscy/manima`. Because
publishing to a public remote is an outward-facing action, it SHALL be performed only
on explicit human confirmation and SHALL NOT be automated by the pipeline.

#### Scenario: Operator confirms publication

- **WHEN** the operator explicitly confirms publishing to `github.com/groscy/manima`
- **THEN** the configured remote is added and the branch is pushed

#### Scenario: No implicit publication

- **WHEN** no explicit confirmation to publish has been given
- **THEN** the repository SHALL NOT be pushed to the public remote
- **AND** no workflow SHALL push project source to it automatically
