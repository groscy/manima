"""End-to-end job-manager tests with fakes — exercises the render path, the generate
pipeline, repair, escalation, cancellation, and state-machine enforcement without Docker,
a GPU, or the network. Async tests run via asyncio.run so no pytest-asyncio is needed.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manima_server.config import ServerConfig  # noqa: E402
from manima_server.core.domain import Job, JobState, RenderMode, RenderOutcome  # noqa: E402
from manima_server.core.job_manager import JobManager  # noqa: E402

GOOD = "from manim import *\n\nclass S(Scene):\n    def construct(self):\n        self.add(Circle())\n"
TWO_SCENES = "from manim import *\nclass A(Scene):\n    def construct(self): pass\nclass B(Scene):\n    def construct(self): pass\n"
BAD_IMPORT = "import os\nos.system('rm -rf /')\n"

_ARTIFACT = Path(tempfile.gettempdir()) / "manima-fake-artifact.mp4"
_ARTIFACT.write_bytes(b"video")


class FakeSandbox:
    def __init__(self, script):
        self._script = script
        self.calls = []
        self.kills = []

    async def run(self, source, *, mode, scene_name=None, quality="low", name=None):
        i = len(self.calls)
        self.calls.append((mode, name))
        return self._script(mode, i, source)

    async def kill(self, name):
        self.kills.append(name)

    def preflight(self):
        pass


class FakeStore:
    def __init__(self):
        self.put_calls = []
        self.preset = {}

    def key_for(self, source, quality):
        return f"k-{abs(hash((source, quality)))}"

    def get(self, key):
        return self.preset.get(key)

    def put(self, key, artifact_path):
        self.put_calls.append(key)
        return f"uri://{key}"

    def reap(self):
        return []


class FakeGenerator:
    def __init__(self, sources, identity="fake-local", gate=None):
        self._sources = list(sources)
        self._i = 0
        self._identity = identity
        self._gate = gate

    @property
    def identity(self):
        return self._identity

    async def generate(self, prompt, *, grounding, repair_source=None, repair_traceback=None):
        if self._gate is not None:
            await self._gate.wait()
        src = self._sources[min(self._i, len(self._sources) - 1)]
        self._i += 1
        return src


class FakeGrounding:
    async def retrieve(self, prompt, k=8):
        return ["Create(...)  # CE, not ShowCreation"]


class DictJobStore:
    def __init__(self):
        self._d = {}

    def create(self, job):
        self._d[job.job_id] = job

    def save(self, job):
        self._d[job.job_id] = job

    def load(self, job_id):
        return self._d.get(job_id)

    def expired(self, now):
        return [j for j in self._d.values() if j.expires_at and j.expires_at <= now]


def _ok(mode):
    return RenderOutcome(ok=True, mode=mode, artifact_path=str(_ARTIFACT))


def _fail(mode, tb):
    return RenderOutcome(ok=False, mode=mode, traceback=tb)


def _manager(sandbox, *, generator=None, escalation=None, config=None):
    return JobManager(
        config or ServerConfig(),
        job_store=DictJobStore(),
        sandbox=sandbox,
        artifact_store=FakeStore(),
        generator=generator,
        grounding=FakeGrounding() if generator else None,
        escalation_generator=escalation,
    )


# -- render path ----------------------------------------------------------------

def test_render_success():
    async def run():
        sb = FakeSandbox(lambda mode, i, src: _ok(mode))
        mgr = _manager(sb)
        jid = mgr.submit_render(GOOD, quality="low", scene_name=None)
        await mgr.wait(jid)
        job = mgr.get(jid)
        assert job.state is JobState.SUCCEEDED
        assert job.artifact_uri and job.artifact_uri.startswith("uri://")
        assert len(job.trace) == 1 and job.trace[0].generator is None
        assert [m for m, _ in sb.calls] == [RenderMode.FULL]
    asyncio.run(run())


def test_render_traceback_no_repair():
    async def run():
        sb = FakeSandbox(lambda mode, i, src: _fail(mode, "NameError: Circl"))
        mgr = _manager(sb)
        jid = mgr.submit_render(GOOD, quality="low", scene_name=None)
        await mgr.wait(jid)
        job = mgr.get(jid)
        assert job.state is JobState.FAILED
        assert "NameError" in job.error
        assert len(sb.calls) == 1  # no repair on the render path
    asyncio.run(run())


def test_render_validation_failure_never_touches_sandbox():
    async def run():
        sb = FakeSandbox(lambda mode, i, src: _ok(mode))
        mgr = _manager(sb)
        jid = mgr.submit_render(BAD_IMPORT, quality="low", scene_name=None)
        await mgr.wait(jid)
        job = mgr.get(jid)
        assert job.state is JobState.FAILED
        assert "validation" in job.error
        assert sb.calls == []  # rejected before any execution
    asyncio.run(run())


def test_render_ambiguous_scene():
    async def run():
        sb = FakeSandbox(lambda mode, i, src: _ok(mode))
        mgr = _manager(sb)
        jid = mgr.submit_render(TWO_SCENES, quality="low", scene_name=None)
        await mgr.wait(jid)
        job = mgr.get(jid)
        assert job.state is JobState.FAILED
        assert "ambiguous" in job.error and "A" in job.error and "B" in job.error
        assert sb.calls == []
    asyncio.run(run())


def test_render_cache_hit_skips_render():
    async def run():
        sb = FakeSandbox(lambda mode, i, src: _ok(mode))
        mgr = _manager(sb)
        # Pre-seed the store so the request is a cache hit.
        store = mgr._store
        store.preset[store.key_for(GOOD, "low")] = "uri://cached"
        jid = mgr.submit_render(GOOD, quality="low", scene_name=None)
        await mgr.wait(jid)
        job = mgr.get(jid)
        assert job.state is JobState.SUCCEEDED
        assert sb.calls == []  # served from cache, no re-render
    asyncio.run(run())


# -- generate path --------------------------------------------------------------

def test_generate_first_pass_success():
    async def run():
        sb = FakeSandbox(lambda mode, i, src: _ok(mode))
        gen = FakeGenerator([GOOD])
        mgr = _manager(sb, generator=gen)
        jid = mgr.submit_generate(GOOD, quality="low", repair_budget=3, allow_escalation=False)
        await mgr.wait(jid)
        job = mgr.get(jid)
        assert job.state is JobState.SUCCEEDED
        assert len(job.trace) == 1 and job.trace[0].generator == "fake-local"
        # probe then full.
        assert [m for m, _ in sb.calls] == [RenderMode.PROBE, RenderMode.FULL]
    asyncio.run(run())


def test_generate_repair_converges():
    async def run():
        # Probe fails on the first candidate, passes on the second.
        def script(mode, i, src):
            if mode is RenderMode.PROBE and "ShowCreation" in src:
                return _fail(mode, "AttributeError: ShowCreation")
            return _ok(mode)
        sb = FakeSandbox(script)
        gen = FakeGenerator([GOOD.replace("Circle()", "ShowCreation(Circle())"), GOOD])
        mgr = _manager(sb, generator=gen)
        jid = mgr.submit_generate(GOOD, quality="low", repair_budget=3, allow_escalation=False)
        await mgr.wait(jid)
        job = mgr.get(jid)
        assert job.state is JobState.SUCCEEDED
        assert len(job.trace) == 2
        assert "ShowCreation" in job.trace[0].traceback  # attempt 1 saw the failure
    asyncio.run(run())


def test_generate_budget_exhausted_no_escalation():
    async def run():
        sb = FakeSandbox(lambda mode, i, src: _fail(mode, "AttributeError: nope"))
        gen = FakeGenerator([GOOD])
        mgr = _manager(sb, generator=gen)
        jid = mgr.submit_generate(GOOD, quality="low", repair_budget=2, allow_escalation=True)
        await mgr.wait(jid)
        job = mgr.get(jid)
        assert job.state is JobState.FAILED
        assert job.best_effort_source is not None
        assert job.last_traceback and "nope" in job.last_traceback
        assert len(job.trace) == 2  # bounded by budget; no escalation (config denies)
        assert not job.escalated
    asyncio.run(run())


def test_generate_escalation_when_all_gates_open():
    async def run():
        # Local probe always fails; escalated candidate passes.
        def script(mode, i, src):
            if "ESCALATED" in src:
                return _ok(mode)
            return _fail(mode, "AttributeError: local")
        sb = FakeSandbox(script)
        gen = FakeGenerator([GOOD])
        esc = FakeGenerator([GOOD + "# ESCALATED"], identity="frontier")
        cfg = ServerConfig()
        object.__setattr__(cfg.generate, "allow_escalation", True)  # gate 1 open
        mgr = _manager(sb, generator=gen, escalation=esc, config=cfg)
        jid = mgr.submit_generate(GOOD, quality="low", repair_budget=2, allow_escalation=True)
        await mgr.wait(jid)
        job = mgr.get(jid)
        assert job.state is JobState.SUCCEEDED
        assert job.escalated
        assert mgr.receipts and mgr.receipts[0].model == "frontier"
    asyncio.run(run())


def test_generate_unavailable_on_render_only():
    async def run():
        sb = FakeSandbox(lambda mode, i, src: _ok(mode))
        mgr = _manager(sb)  # no generator
        try:
            mgr.submit_generate("x", quality="low", repair_budget=3, allow_escalation=False)
        except Exception as exc:
            assert "render-only" in str(exc)
        else:
            raise AssertionError("expected GenerateUnavailable")
    asyncio.run(run())


# -- cancellation ---------------------------------------------------------------

def test_cancel_in_flight_generate():
    async def run():
        gate = asyncio.Event()
        sb = FakeSandbox(lambda mode, i, src: _ok(mode))
        gen = FakeGenerator([GOOD], gate=gate)
        mgr = _manager(sb, generator=gen)
        jid = mgr.submit_generate(GOOD, quality="low", repair_budget=3, allow_escalation=False)
        await asyncio.sleep(0)  # let the worker reach generator.generate()
        ack = await mgr.cancel(jid)
        assert ack["cancelled"] is True
        gate.set()  # release generation; worker should notice the cancel at the probe checkpoint
        await mgr.wait(jid)
        assert mgr.get(jid).state is JobState.CANCELLED
    asyncio.run(run())


def test_cancel_terminal_is_noop():
    async def run():
        sb = FakeSandbox(lambda mode, i, src: _ok(mode))
        mgr = _manager(sb)
        jid = mgr.submit_render(GOOD, quality="low", scene_name=None)
        await mgr.wait(jid)
        ack = await mgr.cancel(jid)
        assert ack["cancelled"] is False and ack.get("already_terminal")
    asyncio.run(run())


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    for name, fn in fns:
        fn()
        print(f"ok  {name}")
    print(f"\n{len(fns)} tests passed")
