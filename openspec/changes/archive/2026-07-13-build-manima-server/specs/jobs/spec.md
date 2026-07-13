# Jobs

## Purpose

Decouple render duration from tool-call duration, and artifact size from the
context window.

## ADDED Requirements

### Requirement: All work SHALL be asynchronous

No MCP tool call SHALL block on a render. Tools enqueue and return a `job_id`.

#### Scenario: Long render does not block

- **WHEN** a 60-second 1080p60 scene is requested
- **THEN** the tool call returns within 2 seconds
- **AND** progress is observable via `job_status` throughout

### Requirement: The system SHALL expose `job_status`

The system SHALL expose a `job_status` tool that MUST return without blocking.

Returns: `state`, `attempt`, `phase`. Cheap. Never blocks.

#### Scenario: Polling during repair

- **WHEN** `job_status` is called during the repair loop
- **THEN** it reports the current attempt number and phase
- **AND** the caller can see that repair is in progress rather than that the
  server has hung

### Requirement: The system SHALL expose `job_result`

The system SHALL expose a `job_result` tool that MUST be valid only in terminal states.

Valid only in terminal states. Returns `artifact_uri`, `source`, and `trace`.

#### Scenario: Result carries a path, not bytes

- **WHEN** a job succeeds
- **THEN** `job_result` returns a filesystem path
- **AND** the video bytes are never inlined into the tool result

#### Scenario: Trace is honest about what happened

- **WHEN** a job succeeded on the third repair attempt after escalation
- **THEN** the trace records: generator identity per attempt, each traceback,
  the attempt count, and the escalation flag
- **AND** a successful result does not conceal a difficult path to it

### Requirement: The system SHALL expose `cancel_job`

The system SHALL expose a `cancel_job` tool that MUST transition a running job to
`CANCELLED` and MUST be a no-op on an already-terminal job.

#### Scenario: Cancel during render

- **WHEN** `cancel_job` is called while a container is rendering
- **THEN** the container is killed
- **AND** the job transitions to `CANCELLED`

#### Scenario: Cancel a terminal job

- **WHEN** `cancel_job` targets an already-terminal job
- **THEN** the call is a no-op and acknowledges as such

### Requirement: Job state SHALL follow a defined machine

Every job SHALL move only along the transitions defined by this state machine; no
other transition is permitted.

States: `QUEUED`, `GENERATING`, `VALIDATING`, `RENDERING`, `SUCCEEDED`, `FAILED`,
`CANCELLED`, `EXPIRED`. The only backward transition is
`RENDERING`/`VALIDATING` → `GENERATING`, which is the repair edge.

#### Scenario: Repair edge

- **WHEN** a probe render fails and budget remains
- **THEN** the job returns to `GENERATING`
- **AND** the attempt counter increments

### Requirement: Artifacts and job logs SHALL be TTL-reaped

Artifacts and job logs SHALL be removed once their retention window elapses, and the
job SHALL transition to `EXPIRED`.

#### Scenario: Retention window elapses

- **WHEN** an artifact exceeds its retention window
- **THEN** it is removed and the job transitions to `EXPIRED`
- **AND** `job_result` on an expired job reports expiry rather than returning a
  dangling path
