"""MANIMA — a local-first MCP server for Manim CE animations.

Two tool surfaces (project.md): ``render_animation`` (thin path, caller-supplied source)
and ``generate_animation`` (thick path, local Apertus 8B). Neither is privileged. The
core is hexagonal — ports in ``core/ports``, adapters in ``adapters`` — and the core
imports no adapter, so ``render_animation`` never depends on the generator (invariant 6).
"""

__version__ = "0.1.0"
