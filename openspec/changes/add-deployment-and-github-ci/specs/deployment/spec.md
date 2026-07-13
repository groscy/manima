## ADDED Requirements

### Requirement: A render-only deployment SHALL stand up with a single command

The system SHALL provide a single-command entrypoint that stands up a working
`render_animation` deployment on any host with Docker, requiring no GPU, no vLLM,
and no Qdrant. Render-only SHALL be the default; the generate path SHALL NOT be a
prerequisite for it (invariant 6).

#### Scenario: Fresh host, render-only default

- **WHEN** an operator runs the deployment entrypoint on a host with only Docker
  installed
- **THEN** the pinned render image is built and the MANIMA server starts with
  `MANIMA_RENDER_ONLY=1`
- **AND** no vLLM, Qdrant, GPU, or hosted-API credential is required for it to
  become serviceable

#### Scenario: Generate-path dependencies are absent

- **WHEN** the render-only deployment starts and no generate-path service is present
- **THEN** the server starts and `render_animation` is serviceable
- **AND** the server SHALL NOT import or require any generate-path dependency

### Requirement: The generate path SHALL be an explicit opt-in profile

The generate path (`generate_animation`, vLLM, Qdrant grounding) SHALL be deployed
only when explicitly enabled, and its host requirements SHALL be declared. Enabling
it SHALL NOT alter the render-only path.

#### Scenario: Operator enables the generate profile

- **WHEN** the operator enables the generate profile
- **THEN** the deployment additionally provisions the generate-path services it owns
- **AND** documents the GPU/VRAM and external-endpoint requirements the profile assumes

#### Scenario: Generate profile disabled by default

- **WHEN** the operator runs the default entrypoint without opting in
- **THEN** no generate-path service is started

### Requirement: Deployment configuration SHALL be captured in a single env file

Every operator-facing configuration knob (the `MANIMA_*` variables read by
`config.py`, endpoints, TTLs, sandbox limits, the render-only flag) SHALL be
enumerated in a single committed example env file with safe defaults. The example
file SHALL NOT contain real secrets.

#### Scenario: Operator configures from the example

- **WHEN** an operator copies the example env file and edits it
- **THEN** every knob needed to run either deployment shape is present and documented
- **AND** the committed example contains no real credential or token

### Requirement: Deployment SHALL be proven by a render smoke test

The deployment SHALL include a smoke test that submits a trivial scene through
`render_animation` and asserts the job reaches `SUCCEEDED` with a retrievable
artifact. A deployment SHALL be considered healthy only if the smoke test passes —
"started" is not "working" (invariant 3).

#### Scenario: Smoke test on a healthy deployment

- **WHEN** the smoke test runs against a freshly started render-only deployment
- **THEN** it submits a trivial scene, polls to terminal, and asserts `SUCCEEDED`
- **AND** asserts a render artifact is retrievable via `job_result`

#### Scenario: Smoke test on a broken deployment

- **WHEN** the render sandbox is misconfigured (e.g. the Docker daemon is unreachable)
- **THEN** the smoke test SHALL fail loudly with a non-zero exit
- **AND** SHALL NOT report the deployment as healthy

### Requirement: The sandbox boundary SHALL NOT be weakened by deployment

No deployment shape SHALL introduce a host-execution path for render, and any
containment trade-off a deployment makes (for example, granting the server access to
a Docker socket to spawn sibling render containers) SHALL be documented explicitly
rather than left implicit.

#### Scenario: Deployment preserves the sandbox invariant

- **WHEN** any deployment shape is used
- **THEN** every render still executes inside a sandboxed container (invariant 1)
- **AND** no deployment option bypasses the sandbox for operator-supplied source

#### Scenario: A containment trade-off is documented

- **WHEN** a deployment shape grants the server access to the host Docker socket
- **THEN** the security implication SHALL be stated plainly in the deployment docs
- **AND** SHALL NOT be presented as equivalent to the un-elevated boundary
