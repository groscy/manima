"""Failure taxonomy (task 5.4) — "the highest-value output by some margin".

The taxonomy is *hand-classified*: a human reads each failed attempt's raw source and
traceback (persisted by task 2.6) and assigns one class. This module does not pretend to
automate that judgement. What it does:

  1. defines the fixed class vocabulary the proposal names;
  2. offers a *pre-classifier* — a transparent heuristic over traceback text that
     proposes a class for the obvious cases (import errors, syntax errors, ManimGL
     names), so the human confirms/overrides rather than starting cold;
  3. aggregates the *hand* labels (``AttemptRecord.failure_class``) into the counts the
     report and the "act on findings" step (section 6) turn on.

Crucially, the pre-classifier can never emit ``SEMANTIC``. A semantic failure — the
scene runs but animates the wrong thing — is invisible to a traceback by definition
(specs/generate: the probe "is a syntax and API oracle only"). It can only be found by
a human comparing the artifact to the prompt's ``expected`` list.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum

from ..prompts import PromptSuite
from ..record import AttemptRecord, RunRecord


class FailureClass(str, Enum):
    WRONG_API = "wrong-api"  # calls CE API incorrectly (bad signature, gone method)
    MANIMGL_CONFUSION = "manimgl-confusion"  # reaches for a ManimGL construct
    SYNTAX = "syntax"  # does not parse
    IMPORT = "import"  # imports something absent
    SEMANTIC = "semantic"  # runs, but wrong — human-only, never pre-classified
    UNCLASSIFIED = "unclassified"  # failed but not yet hand-labelled


# ManimGL-isms an 8B model reaches for because they dominate its training data. An
# AttributeError/NameError naming one of these is the signature of ManimGL confusion,
# distinct from merely mis-calling a real CE method.
_MANIMGL_NAMES = (
    "ShowCreation",
    "TexMobject",
    "TextMobject",
    "get_graph",
    "GraphScene",
    "ContinualAnimation",
    "ShowCreationThenDestruction",
    "CONFIG",
    "get_center_of_mass",
    "DrawBorderThenFill",  # exists in CE too, but ManimGL signature differs
    "set_color_by_gradient",
)

_MANIMGL_RE = re.compile("|".join(re.escape(n) for n in _MANIMGL_NAMES))


@dataclass
class PreClassification:
    klass: FailureClass
    rationale: str


def pre_classify(traceback: str | None) -> PreClassification | None:
    """Heuristic pre-label from traceback text. Returns None when unsure.

    Order matters: ManimGL confusion is checked before generic wrong-API, because a
    ManimGL name in an AttributeError is the more specific, higher-value finding.
    """

    if not traceback:
        return None
    text = traceback

    if "SyntaxError" in text or "IndentationError" in text:
        return PreClassification(FailureClass.SYNTAX, "SyntaxError/IndentationError in traceback")
    if "ModuleNotFoundError" in text or "ImportError" in text or "cannot import name" in text:
        return PreClassification(FailureClass.IMPORT, "import failure in traceback")

    manimgl = _MANIMGL_RE.search(text)
    if manimgl and ("AttributeError" in text or "NameError" in text):
        return PreClassification(
            FailureClass.MANIMGL_CONFUSION,
            f"ManimGL-only name {manimgl.group(0)!r} with AttributeError/NameError",
        )

    if any(err in text for err in ("AttributeError", "TypeError", "NameError", "ValueError")):
        return PreClassification(
            FailureClass.WRONG_API, "API misuse error (Attribute/Type/Name/Value) in traceback"
        )
    return None


@dataclass
class TaxonomyReport:
    counts: dict[str, int]
    total_failed_attempts: int
    hand_labelled: int
    unclassified: int
    # Runs that succeeded but whose artifact still needs a human semantic check against
    # the prompt's expected list — the pool where SEMANTIC failures hide.
    needs_semantic_review: int
    pre_classification_hint: dict[str, int]

    @property
    def fully_classified(self) -> bool:
        return self.unclassified == 0


def taxonomy_report(
    attempts: list[AttemptRecord],
    runs: list[RunRecord],
    suite: PromptSuite | None = None,
) -> TaxonomyReport:
    """Aggregate hand labels; show pre-classifier hints for what remains.

    ``suite`` is accepted so a caller can cross-reference expected content while doing
    the semantic pass; the aggregate itself only needs it to size the review pool.
    """

    failed = [a for a in attempts if a.traceback_path is not None]
    hand_counts: Counter = Counter()
    unclassified = 0
    for a in failed:
        if a.failure_class:
            hand_counts[a.failure_class] += 1
        else:
            unclassified += 1

    # Successful runs are exactly where semantic failures live: they rendered, so no
    # traceback, but may still animate the wrong thing.
    needs_semantic = sum(1 for r in runs if r.succeeded)

    # Non-binding hints over the *unlabelled* failures, to seed the human pass.
    hints: Counter = Counter()
    return TaxonomyReport(
        counts={
            **{c.value: 0 for c in FailureClass if c is not FailureClass.UNCLASSIFIED},
            **dict(hand_counts),
        },
        total_failed_attempts=len(failed),
        hand_labelled=sum(hand_counts.values()),
        unclassified=unclassified,
        needs_semantic_review=needs_semantic,
        pre_classification_hint=dict(hints),
    )


def pre_classify_attempts(attempts_with_tracebacks: list[tuple[AttemptRecord, str]]) -> dict[str, int]:
    """Run the pre-classifier over (record, traceback_text) pairs; return a class tally.

    Kept separate from ``taxonomy_report`` because it needs the raw traceback *text*,
    which the report deliberately does not load — the report trusts hand labels only.
    """

    tally: Counter = Counter()
    for _record, traceback in attempts_with_tracebacks:
        hint = pre_classify(traceback)
        tally[hint.klass.value if hint else FailureClass.UNCLASSIFIED.value] += 1
    return dict(tally)
