"""Apertus load-test harness.

An ordinary MCP client that drives MANIMA under load, external to the server (change
001). It never reaches into server internals — only the five documented tools. See
``proposal.md`` and ``tasks.md`` in ``openspec/changes/001-apertus-load-harness``.

Nothing in this package can be exercised end-to-end until a MANIMA server exists to
spawn (tasks.md sequencing note). It is written against the specs in ``openspec/specs``;
wire-detail assumptions are marked ASSUMPTION in ``contract`` and side-channel gaps are
recorded as findings rather than papered over.
"""

__version__ = "0.1.0"
