"""The pinned Manim CE version — the single source of truth (design D8, task 1.2).

This one constant flows into three places that MUST agree:

  1. the render image (docker/Dockerfile installs exactly this version),
  2. the grounding corpus (built from exactly this version's API), and
  3. the artifact hash (``manim_version`` participates in the content key).

Bumping it means rebuilding all three, in that order (image -> corpus -> hash). Drift
between them is the precise failure mode grounding exists to prevent, so nothing else in
the codebase should hard-code a Manim version string — import this.
"""

# Open question in design.md — confirm the exact pin before the first corpus build.
# 0.18.1 is the current stable Manim CE line; used as the concrete default.
MANIM_CE_VERSION = "0.18.1"
