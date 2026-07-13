"""Offline tests for the filesystem store and SQLite job store — no Docker/GPU/network."""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manima_server.adapters.fs_store import FsArtifactStore  # noqa: E402
from manima_server.adapters.sqlite_jobs import SqliteJobStore  # noqa: E402
from manima_server.core.domain import Attempt, Job, JobState, Tool  # noqa: E402


def test_fs_store_put_get_and_cache_hit(tmp_path):
    src_video = tmp_path / "render.mp4"
    src_video.write_bytes(b"fake-video-bytes")
    store = FsArtifactStore(tmp_path / "store", ttl_s=3600)

    key = store.key_for("from manim import *", "low")
    assert store.get(key) is None  # cold

    path = store.put(key, str(src_video))
    assert store.get(key) == path
    assert Path(path).read_bytes() == b"fake-video-bytes"

    # Second put is a no-op cache hit returning the same path.
    assert store.put(key, str(src_video)) == path


def test_fs_store_reaps_old_artifacts(tmp_path):
    src_video = tmp_path / "r.mp4"
    src_video.write_bytes(b"x")
    store = FsArtifactStore(tmp_path / "store", ttl_s=1.0)
    key = store.key_for("s", "low")
    path = store.put(key, str(src_video))

    # Backdate mtime beyond the TTL.
    old = time.time() - 10
    os.utime(path, (old, old))
    reaped = store.reap()
    assert key in reaped and store.get(key) is None


def test_sqlite_job_roundtrip_preserves_trace(tmp_path):
    store = SqliteJobStore(tmp_path / "jobs.db")
    job = Job(job_id="j1", tool=Tool.GENERATE, params={"prompt": "draw a circle"})
    job.state = JobState.GENERATING
    job.add_attempt(Attempt(0, generator="apertus", source="v1", traceback="boom"))
    job.escalated = False
    store.create(job)

    loaded = store.load("j1")
    assert loaded is not None
    assert loaded.tool is Tool.GENERATE
    assert loaded.state is JobState.GENERATING
    assert loaded.params == {"prompt": "draw a circle"}
    assert len(loaded.trace) == 1 and loaded.trace[0].traceback == "boom"
    assert loaded.attempt == 1

    # Upsert on save.
    loaded.state = JobState.SUCCEEDED
    loaded.artifact_uri = "/store/aa/aa.mp4"
    store.save(loaded)
    assert store.load("j1").state is JobState.SUCCEEDED
    store.close()


def test_sqlite_expired_query(tmp_path):
    store = SqliteJobStore(tmp_path / "jobs.db")
    now = time.time()
    fresh = Job(job_id="fresh", tool=Tool.RENDER, expires_at=now + 1000)
    stale = Job(job_id="stale", tool=Tool.RENDER, expires_at=now - 10)
    stale.state = JobState.SUCCEEDED
    store.create(fresh)
    store.create(stale)

    expired = store.expired(now)
    ids = {j.job_id for j in expired}
    assert "stale" in ids and "fresh" not in ids
    store.close()


if __name__ == "__main__":
    import tempfile

    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    for name, fn in fns:
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
        print(f"ok  {name}")
    print(f"\n{len(fns)} tests passed")
