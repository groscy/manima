# Sandbox

## Purpose

Contain the execution of untrusted Python. Manim renders by running arbitrary
code; this capability is what stands between a hostile or broken scene and the
host.

## Requirements

### Requirement: All render execution SHALL be sandboxed

Every render — generated or operator-supplied, probe or full-quality — SHALL
execute inside a rootless Docker container. There SHALL be no code path that
executes Manim source on the host.

#### Scenario: Operator-supplied source is sandboxed

- **WHEN** `render_animation` is called with source the operator wrote themselves
- **THEN** the source executes in a container with the same controls applied to
  generated source
- **AND** no configuration option exists to bypass this

#### Scenario: Docker daemon unavailable

- **WHEN** the Docker daemon is unreachable at server startup
- **THEN** the server SHALL fail to start, loudly
- **AND** SHALL NOT fall back to host execution under any circumstance

### Requirement: The sandbox SHALL deny network access

Every render container SHALL run with networking disabled, so no scene can reach the
network.

#### Scenario: Scene attempts network egress

- **WHEN** a scene attempts to open a socket or resolve a hostname
- **THEN** the attempt fails because the container runs with `--network=none`
- **AND** the failure surfaces as an ordinary render traceback

### Requirement: The sandbox SHALL enforce resource limits

Each container SHALL run with a memory cap, a CPU quota, and a wall-clock
timeout. Probe renders and full renders SHALL have separate timeout budgets.

#### Scenario: Infinite loop in construct()

- **WHEN** a scene loops forever
- **THEN** the wall-clock timeout elapses
- **AND** the container is killed
- **AND** the job transitions to `FAILED` with a timeout reason
- **AND** the server remains responsive to other calls

#### Scenario: Runaway memory allocation

- **WHEN** a scene exhausts its memory cap
- **THEN** the container is OOM-killed
- **AND** only that job fails; the host and other jobs are unaffected

### Requirement: The sandbox SHALL drop privileges

Containers SHALL run rootless, as a non-root user, with `--cap-drop=ALL`, a
read-only root filesystem, and a restricted seccomp profile. TeX shell-escape
SHALL be explicitly disabled.

#### Scenario: Scene attempts host filesystem access

- **WHEN** a scene attempts to read or write outside its mounted working set
- **THEN** the attempt fails
- **AND** host state is unchanged

### Requirement: Static validation SHALL precede execution but SHALL NOT be relied upon

Candidate source SHALL be AST-validated against an allowlist before execution.
Rejections SHALL produce a structured message the repair loop can act on.

#### Scenario: Validation is a fast-fail, not a boundary

- **WHEN** validation passes source that later proves hostile
- **THEN** the sandbox contains it
- **AND** this is the expected division of responsibility, not a defect
