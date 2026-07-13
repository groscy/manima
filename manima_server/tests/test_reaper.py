"""TTL reaper test (tasks 11.1-11.2) — real FS store + SQLite job store, no server."""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manima_server.adapters.fs_store import FsArtifactStore  # noqa: E402
from manima_server.adapters.sqlite_jobs import SqliteJobStore  # noqa: E402
from manima_server.core.domain import Job, JobState, Tool  # noqa: E402
from manima_server.core.reaper import Reaper  # noqa: E402


def test_reaper_expires_job_and_drops_artifact(tmp_path):
    store = FsArtifactStore(tmp_path / "store", ttl_s=1.0)
    jobs = SqliteJobStore(tmp_path / "jobs.db")

    src = tmp_path / "r.mp4"
    src.write_bytes(b"video")
    key = store.key_for("s", "low")
    uri = store.put(key, str(src))

    now = time.time()
    job = Job(job_id="j", tool=Tool.RENDER, artifact_uri=uri, expires_at=now - 10)
    job.state = JobState.SUCCEEDED
    jobs.create(job)

    # Backdate the artifact so the store reaps it too.
    old = now - 100
    os.utime(uri, (old, old))

    expired = Reaper(jobs, store).reap(now)
    assert expired == 1
    reloaded = jobs.load("j")
    assert reloaded.state is JobState.EXPIRED
    assert reloaded.artifact_uri is None  # no dangling path (11.2)
    assert store.get(key) is None
    jobs.close()


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        test_reaper_expires_job_and_drops_artifact(Path(d))
    print("ok  test_reaper_expires_job_and_drops_artifact")
