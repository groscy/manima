"""SQLite-backed durable job store (task 4.1, design D7).

Job records, state, attempt count, and the full trace persist in SQLite on the WSL2
filesystem. Durability matters because ``job_result`` must return an honest trace across
the job's life (and across a server restart), and TTL reaping needs a queryable
``expires_at``. SQLite gives all of that with no external daemon.

The trace and params serialise to JSON columns; ``load`` reconstructs domain objects so
the core only ever sees ``Job``/``Attempt``, never rows.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from ..core.domain import Attempt, Job, JobState, Tool

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    tool        TEXT NOT NULL,
    state       TEXT NOT NULL,
    attempt     INTEGER NOT NULL,
    phase       TEXT,
    params      TEXT NOT NULL,
    trace       TEXT NOT NULL,
    artifact_uri TEXT,
    source      TEXT,
    error       TEXT,
    escalated   INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    expires_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_jobs_expires ON jobs(expires_at);
"""


class SqliteJobStore:
    """`JobStore` adapter. One connection guarded by a lock — the async job manager runs
    in a single event loop, but the lock keeps the reaper task and workers safe."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def create(self, job: Job) -> None:
        self.save(job)

    def save(self, job: Job) -> None:
        row = _to_row(job)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jobs (job_id, tool, state, attempt, phase, params, trace,
                                  artifact_uri, source, error, escalated,
                                  created_at, updated_at, expires_at)
                VALUES (:job_id, :tool, :state, :attempt, :phase, :params, :trace,
                        :artifact_uri, :source, :error, :escalated,
                        :created_at, :updated_at, :expires_at)
                ON CONFLICT(job_id) DO UPDATE SET
                    state=excluded.state, attempt=excluded.attempt, phase=excluded.phase,
                    params=excluded.params, trace=excluded.trace,
                    artifact_uri=excluded.artifact_uri, source=excluded.source,
                    error=excluded.error, escalated=excluded.escalated,
                    updated_at=excluded.updated_at, expires_at=excluded.expires_at
                """,
                row,
            )
            self._conn.commit()

    def load(self, job_id: str) -> Job | None:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cur.fetchone()
        return _from_row(row) if row else None

    def expired(self, now: float) -> list[Job]:
        """Non-terminal-expired jobs whose retention window has elapsed."""

        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM jobs WHERE expires_at IS NOT NULL AND expires_at <= ? "
                "AND state != ?",
                (now, JobState.EXPIRED.value),
            )
            rows = cur.fetchall()
        return [_from_row(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _to_row(job: Job) -> dict:
    return {
        "job_id": job.job_id,
        "tool": job.tool.value,
        "state": job.state.value,
        "attempt": job.attempt,
        "phase": job.phase,
        "params": json.dumps(job.params),
        "trace": json.dumps([_attempt_to_dict(a) for a in job.trace]),
        "artifact_uri": job.artifact_uri,
        "source": job.source,
        "error": job.error,
        "escalated": 1 if job.escalated else 0,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "expires_at": job.expires_at,
    }


def _from_row(row: sqlite3.Row) -> Job:
    return Job(
        job_id=row["job_id"],
        tool=Tool(row["tool"]),
        state=JobState(row["state"]),
        attempt=row["attempt"],
        phase=row["phase"],
        params=json.loads(row["params"]),
        trace=[_attempt_from_dict(d) for d in json.loads(row["trace"])],
        artifact_uri=row["artifact_uri"],
        source=row["source"],
        error=row["error"],
        escalated=bool(row["escalated"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expires_at=row["expires_at"],
    )


def _attempt_to_dict(a: Attempt) -> dict:
    return {
        "index": a.index,
        "generator": a.generator,
        "source": a.source,
        "traceback": a.traceback,
        "escalated": a.escalated,
    }


def _attempt_from_dict(d: dict) -> Attempt:
    return Attempt(
        index=d["index"],
        generator=d.get("generator"),
        source=d.get("source"),
        traceback=d.get("traceback"),
        escalated=d.get("escalated", False),
    )
