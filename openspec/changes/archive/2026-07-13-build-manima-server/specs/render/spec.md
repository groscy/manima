# Render

## Purpose

The thin path. Execute Manim CE source supplied by the caller and produce a video
artifact. No generator involved.

## ADDED Requirements

### Requirement: The system SHALL expose a `render_animation` tool

The system SHALL expose an MCP tool `render_animation` that renders caller-supplied
Manim CE source, without involving the generator.

Arguments: `source` (required), `quality` (optional, default low), `scene_name`
(optional; inferred if a single Scene subclass is present).

Returns: `job_id`, immediately.

#### Scenario: Valid source renders

- **WHEN** `render_animation` is called with source defining one Scene subclass
- **THEN** a `job_id` is returned within 2 seconds
- **AND** the job proceeds through `VALIDATING` → `RENDERING` → `SUCCEEDED`
- **AND** `job_result` returns a filesystem path to the rendered video

#### Scenario: Source with a traceback

- **WHEN** the supplied source raises during render
- **THEN** the job transitions to `FAILED`
- **AND** `job_result` returns the traceback
- **AND** no repair is attempted — the caller wrote this source, so repair is
  the caller's business, not the server's

#### Scenario: Ambiguous scene

- **WHEN** source defines multiple Scene subclasses and `scene_name` is omitted
- **THEN** the job fails with a message naming the candidates

### Requirement: Renders SHALL support full LaTeX

The render image SHALL include full TeX Live.

#### Scenario: Scene uses an uncommon LaTeX package

- **WHEN** a scene's `Tex` or `MathTex` requires a package outside a basic install
- **THEN** the render succeeds without network access or on-demand installation

### Requirement: Artifacts SHALL be content-addressed

The artifact key SHALL be a hash of `(source, quality, manim_version)`.

#### Scenario: Identical request served from cache

- **WHEN** the same source is submitted twice at the same quality
- **THEN** the second job resolves to the existing artifact without re-rendering

#### Scenario: Manim version bumped

- **WHEN** the pinned Manim CE version changes
- **THEN** previously cached artifacts do not collide with new renders,
  because `manim_version` participates in the hash
