"""Unit tests for the pure core — no Docker, no GPU, no network.

Covers the domain state machine, content-addressing, the AST validator, and the
escalation gate. Runs under pytest, or directly (`python tests/test_core.py`).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manima_server.core.domain import Attempt, Job, JobState, Tool  # noqa: E402
from manima_server.core import state_machine as sm  # noqa: E402
from manima_server.core.hashing import content_key  # noqa: E402
from manima_server.core import validator  # noqa: E402
from manima_server.core.escalation import should_escalate  # noqa: E402


def test_terminal_states():
    assert JobState.SUCCEEDED.terminal and JobState.EXPIRED.terminal
    assert not JobState.QUEUED.terminal and not JobState.RENDERING.terminal


def test_state_machine_forward_and_terminal():
    assert sm.can_transition(JobState.QUEUED, JobState.VALIDATING)
    assert sm.can_transition(JobState.VALIDATING, JobState.RENDERING)
    assert sm.can_transition(JobState.RENDERING, JobState.SUCCEEDED)
    assert sm.can_transition(JobState.SUCCEEDED, JobState.EXPIRED)
    # No resurrection from a terminal state.
    assert not sm.can_transition(JobState.SUCCEEDED, JobState.RENDERING)
    assert not sm.can_transition(JobState.EXPIRED, JobState.SUCCEEDED)
    # Can't skip validation straight to success.
    assert not sm.can_transition(JobState.QUEUED, JobState.SUCCEEDED)


def test_state_machine_repair_is_the_only_backward_edge():
    assert sm.is_repair_edge(JobState.RENDERING, JobState.GENERATING)
    assert sm.is_repair_edge(JobState.VALIDATING, JobState.GENERATING)
    assert sm.can_transition(JobState.RENDERING, JobState.GENERATING)
    # GENERATING never goes back to QUEUED — repair is the only backward move.
    assert not sm.can_transition(JobState.GENERATING, JobState.QUEUED)
    assert not sm.is_repair_edge(JobState.RENDERING, JobState.SUCCEEDED)


def test_assert_transition_raises_on_illegal():
    sm.assert_transition(JobState.QUEUED, JobState.GENERATING)  # ok
    try:
        sm.assert_transition(JobState.QUEUED, JobState.SUCCEEDED)
    except sm.InvalidTransition:
        pass
    else:
        raise AssertionError("expected InvalidTransition")


def test_content_key_deterministic_and_sensitive():
    k1 = content_key("src", "low", "0.18.1")
    assert k1 == content_key("src", "low", "0.18.1")  # deterministic
    assert k1 != content_key("src", "high", "0.18.1")  # quality participates
    assert k1 != content_key("src", "low", "0.19.0")   # version participates
    assert k1 != content_key("src ", "low", "0.18.1")  # source participates
    # Length-prefixing blocks boundary-collision aliasing.
    assert content_key("ab", "c", "v") != content_key("a", "bc", "v")


def test_validator_accepts_a_plain_scene():
    src = "from manim import *\n\nclass S(Scene):\n    def construct(self):\n        self.add(Circle())\n"
    assert validator.validate(src).ok


def test_validator_rejects_host_reach_and_dynamic_exec():
    assert not validator.validate("import os\nos.system('x')").ok
    assert not validator.validate("exec('x')").ok
    assert not validator.validate("import socket").ok
    r = validator.validate("().__class__.__bases__")
    assert not r.ok and "not allowed" in r.as_repair_message()


def test_validator_reports_syntax_error_as_violation():
    r = validator.validate("def broken(:\n")
    assert not r.ok and "syntax error" in r.violations[0].message


def test_scene_name_discovery():
    src = "from manim import *\nclass A(Scene): pass\nclass B(ThreeDScene): pass\nclass C: pass\n"
    assert validator.scene_names(src) == ["A", "B"]


def test_escalation_triple_gate():
    # Only all-three-open escalates.
    assert should_escalate(config_permits=True, call_allows=True, budget_exhausted=True)
    for combo in [
        dict(config_permits=False, call_allows=True, budget_exhausted=True),
        dict(config_permits=True, call_allows=False, budget_exhausted=True),
        dict(config_permits=True, call_allows=True, budget_exhausted=False),
    ]:
        assert not should_escalate(**combo)


def test_job_trace_helpers():
    job = Job(job_id="j", tool=Tool.GENERATE)
    job.add_attempt(Attempt(0, generator="apertus", source="v1", traceback="boom"))
    job.add_attempt(Attempt(1, generator="apertus", source="v2", traceback=None))
    assert job.attempt == 2
    assert job.last_traceback == "boom"
    assert job.best_effort_source == "v2"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
