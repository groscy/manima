"""The escalation gate (task 9.2, ADR-003, specs/generate).

Escalation to a hosted model is **deny-by-default** and fires only when *all three* gates
are open. Encoding it as one pure predicate keeps the invariant in a single, testable
place — no adapter and no tool handler decides this on its own.

The three gates, per ADR-003:
  1. the server config permits escalation at all,
  2. the individual call passed ``allow_escalation: true``, and
  3. the local repair budget is exhausted.

With any gate shut, the local path runs to completion and no egress is attempted — the
sovereignty property, verifiable by running air-gapped (task 9.4).
"""

from __future__ import annotations

from dataclasses import dataclass


def should_escalate(
    *, config_permits: bool, call_allows: bool, budget_exhausted: bool
) -> bool:
    """True only when every gate is open. Any single closed gate denies escalation."""

    return config_permits and call_allows and budget_exhausted


@dataclass(frozen=True)
class EscalationReceipt:
    """Emitted whenever escalation fires (task 9.3, specs/generate).

    Records the job, the model called, token counts, and the reason the local path
    failed — so an escalation is always auditable after the fact.
    """

    job_id: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    reason: str

    def as_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reason": self.reason,
        }
