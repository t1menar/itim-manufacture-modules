"""Job state in SQLite: one row per step visit (`step_key`), plus the Claude session of each (run, mode).

The step handler stores the job and parks the attempt (`ctx.wait`); the worker picks queued jobs one at a time and
finishes the attempt with `Module.complete` / `Module.fail`. A restart resumes `queued` and `running` jobs.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = """
create table if not exists jobs (
  step_key text primary key,
  run_id text not null,
  mode text not null,
  visit integer not null,
  handle text not null,
  inp text not null,
  state text not null,            -- queued | running | done | failed
  attempts integer not null default 0,
  output text,
  error text,
  created real not null,
  updated real not null
);
create table if not exists sessions (
  run_id text not null,
  mode text not null,
  session_id text not null,
  primary key (run_id, mode)
);
create table if not exists episodes (
  run_id text primary key,
  episode_dir text not null
);
"""


@dataclass
class Job:
    step_key: str
    run_id: str
    mode: str
    visit: int
    handle: str
    inp: dict[str, Any]
    state: str = "queued"
    attempts: int = 0
    output: dict[str, Any] | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    def _row(self, r: sqlite3.Row) -> Job:
        return Job(
            r["step_key"], r["run_id"], r["mode"], r["visit"], r["handle"], json.loads(r["inp"]), r["state"],
            r["attempts"], json.loads(r["output"]) if r["output"] else None, r["error"], r["created"],
        )  # fmt: skip

    def get(self, step_key: str) -> Job | None:
        with self._lock:
            r = self._db.execute("select * from jobs where step_key = ?", (step_key,)).fetchone()
        return self._row(r) if r else None

    def put(self, job: Job) -> Job:
        """Insert a new job, or point an existing unfinished one at the new attempt handle."""
        now = time.time()
        with self._lock:
            old = self._db.execute("select state from jobs where step_key = ?", (job.step_key,)).fetchone()
            if old is None:
                self._db.execute(
                    "insert into jobs values (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (job.step_key, job.run_id, job.mode, job.visit, job.handle, json.dumps(job.inp), "queued", 0,
                     None, None, now, now),
                )  # fmt: skip
            elif old["state"] == "failed":  # an operator retried the step: start over
                self._db.execute(
                    "update jobs set handle = ?, inp = ?, state = 'queued', attempts = 0, error = null, updated = ?"
                    " where step_key = ?",
                    (job.handle, json.dumps(job.inp), now, job.step_key),
                )
            else:
                self._db.execute(
                    "update jobs set handle = ?, updated = ? where step_key = ?", (job.handle, now, job.step_key)
                )
        got = self.get(job.step_key)
        assert got is not None
        return got

    def next_job(self) -> Job | None:
        """The oldest job to work on; a `running` one first (it was interrupted by a restart)."""
        with self._lock:
            r = self._db.execute(
                "select * from jobs where state in ('running', 'queued')"
                " order by case state when 'running' then 0 else 1 end, created limit 1"
            ).fetchone()
        return self._row(r) if r else None

    def set_state(self, step_key: str, state: str, *, output: dict[str, Any] | None = None, error: str | None = None,
                  attempts: int | None = None) -> None:  # fmt: skip
        with self._lock:
            self._db.execute(
                "update jobs set state = ?, output = coalesce(?, output), error = ?,"
                " attempts = coalesce(?, attempts), updated = ? where step_key = ?",
                (state, json.dumps(output) if output is not None else None, error, attempts, time.time(), step_key),
            )

    def jobs(self, limit: int = 20) -> list[Job]:
        with self._lock:
            rows = self._db.execute("select * from jobs order by updated desc limit ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def session(self, run_id: str, mode: str) -> str | None:
        with self._lock:
            r = self._db.execute(
                "select session_id from sessions where run_id = ? and mode = ?", (run_id, mode)
            ).fetchone()
        return str(r["session_id"]) if r else None

    def set_session(self, run_id: str, mode: str, session_id: str) -> None:
        with self._lock:
            self._db.execute(
                "insert into sessions values (?,?,?)"
                " on conflict(run_id, mode) do update set session_id = excluded.session_id",
                (run_id, mode, session_id),
            )

    def episode(self, run_id: str) -> str | None:
        with self._lock:
            r = self._db.execute("select episode_dir from episodes where run_id = ?", (run_id,)).fetchone()
        return str(r["episode_dir"]) if r else None

    def set_episode(self, run_id: str, episode_dir: str) -> None:
        with self._lock:
            self._db.execute("insert or replace into episodes values (?, ?)", (run_id, episode_dir))
