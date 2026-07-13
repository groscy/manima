"""Adapters — concrete implementations of the core ports (design D1).

Nothing in the core imports this package. Import direction is one-way: adapters depend on
``core.ports`` and ``core.domain``; the core never depends on an adapter. The generate-path
adapters (vLLM, Qdrant, escalation) import their third-party clients lazily so a
render-only deployment need not install them (invariant 6).
"""
