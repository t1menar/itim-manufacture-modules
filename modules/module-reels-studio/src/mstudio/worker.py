"""The worker: takes stored jobs one at a time and drives Claude Code through them.

For each job:
1. usage gate: if a usage window has less than `min_left` left (or is exhausted), tell the owner and sleep until
   it resets;
2. a headless Claude Code run in the episode folder (a new session, or the stored one resumed for revisions,
   retries and limit pauses);
3. the result file the agent wrote is validated; video files are uploaded to S3;
4. the parked platform attempt is finished with `complete` (or `fail` after the error rounds are used up).
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from mstudio.claude import Claude, LimitHit, StageFailed
from mstudio.episodes import PostResult, ResultInvalid, ScriptResult, new_episode_dir, prompt, read_result
from mstudio.notify import Notifier
from mstudio.settings import Settings
from mstudio.store import Job, Store

log = logging.getLogger("mstudio.worker")

PROBE_EVERY_S = 600.0  # usage info older than this is refreshed before a run
RESET_SLACK_S = 90.0  # wait a little past the announced reset


class Finisher(Protocol):
    async def complete(self, handle: str, output: dict[str, Any], cost_usd: float | None) -> None: ...
    async def fail(self, handle: str, message: str, code: str) -> None: ...


class Uploader(Protocol):
    def put_file(self, key: str, path: Path, content_type: str) -> str: ...  # returns the s3:// ref


Sleep = Callable[[float], Awaitable[None]]


@dataclass
class Outcome:
    output: dict[str, Any]
    cost_usd: float


def _when(ts: float) -> str:
    return time.strftime("%H:%M %d.%m", time.localtime(ts))


class Worker:
    def __init__(
        self, settings: Settings, store: Store, claude: Claude, notifier: Notifier, finisher: Finisher,
        uploader: Uploader | None, sleep: Sleep = asyncio.sleep,
    ) -> None:  # fmt: skip
        self.s, self.store, self.claude, self.notify = settings, store, claude, notifier
        self.finisher, self.uploader, self._sleep = finisher, uploader, sleep
        self.wake = asyncio.Event()

    # ------------------------------------------------------------------ loop
    async def forever(self) -> None:
        while True:
            job = self.store.next_job()
            if job is None:
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=30)
                except TimeoutError:
                    pass
                continue
            try:
                await self.process(job)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - never let one job kill the loop
                log.exception("job %s crashed", job.step_key)
                await self.notify.send(f"❌ Reels studio crashed on {job.mode} ({job.run_id[:8]}): {e!r}"[:900])
                self.store.set_state(job.step_key, "failed", error=repr(e))
                await self._fail(job, f"worker crashed: {e!r}", "worker_crashed")

    async def process(self, job: Job) -> None:
        # a job still `running` was cut off by a restart (shutdown, crash): continue its session, do not start over
        interrupted = job.state == "running" and self.store.session(job.run_id, job.mode) is not None
        self.store.set_state(job.step_key, "running")
        ep = self._episode(job)
        title = str((job.inp.get("idea") or {}).get("title") or ep.name)
        rev = job.inp.get("revision") or {}
        if interrupted:
            await self.notify.send(f"▶️ resuming {job.mode} for “{title}” after a restart")
        elif job.attempts == 0:
            what = "revising" if rev.get("comment") else "starting"
            await self.notify.send(f"🎬 {what} {job.mode} for “{title}” ({ep.parent.name}/{ep.name})")
        rounds = 0
        attempts = job.attempts
        cost = 0.0
        fix: str | None = "continue" if interrupted else None
        while True:
            await self._usage_gate(ep)
            started = time.time()
            try:
                text, cost_run = await self._run(job, ep, fix)
                cost += cost_run
                out = self._collect(job, ep, started)
                break
            except LimitHit as e:
                await self.notify.send(f"⏸ Usage limit ({e.window}). “{title}” continues after {_when(e.resets_at)}.")
                await self._sleep_until(e.resets_at)
                fix = "continue"
                continue
            except (StageFailed, ResultInvalid) as e:
                attempts += 1
                self.store.set_state(job.step_key, "running", error=str(e)[:4000], attempts=attempts)
                log.warning("job %s attempt %d: %s", job.step_key, attempts, e)
                if attempts % self.s.max_attempts:
                    fix = f"error: {str(e)[:3000]}"
                    continue
                rounds += 1
                if rounds > self.s.max_rounds:
                    await self.notify.send(f"❌ “{title}” {job.mode} failed {attempts}×, giving up.\n{str(e)[:700]}")
                    self.store.set_state(job.step_key, "failed", error=str(e)[:4000])
                    await self._fail(
                        job, f"{job.mode} failed after {attempts} attempts: {str(e)[:500]}", "studio_failed"
                    )
                    return
                resume = self._next_reset()
                await self.notify.send(
                    f"⚠️ “{title}” {job.mode} failed {attempts}×: {str(e)[:600]}\nRetrying after {_when(resume)}."
                )
                await self._sleep_until(resume)
                fix = f"error: {str(e)[:3000]}"
        self.store.set_state(job.step_key, "done", output=out.output, error=None)
        await self._complete(job, out.output, cost or None)
        log.info("job %s done (%s), %s", job.step_key, text[:200] if text else "", ep)

    # ------------------------------------------------------------------ pieces
    def _episode(self, job: Job) -> Path:
        known = self.store.episode(job.run_id)
        if known and Path(known).is_dir():
            return Path(known)
        given = job.inp.get("episode")
        ep = (
            Path(given)
            if given and Path(given).is_dir()
            else new_episode_dir(job.inp.get("idea") or {}, self.s.reels_dir)
        )
        self.store.set_episode(job.run_id, str(ep))
        return ep

    async def _run(self, job: Job, ep: Path, fix: str | None) -> tuple[str, float]:
        """One Claude Code turn for the job; `fix` is set when continuing after a pause or an error."""
        logf = self.s.log_dir / f"{job.run_id}-{job.mode}.jsonl"
        sid = self.store.session(job.run_id, job.mode)
        rev = job.inp.get("revision") or {}
        values = {
            "episode": str(ep), "series": ep.parent.name, "reels": str(self.s.reels_dir),
            "idea": json.dumps(job.inp.get("idea") or {}, ensure_ascii=False, indent=1),
            "comment": str(rev.get("comment") or "").strip() or "(no comment)", "round": str(rev.get("round") or 1),
            "result": f"factory/{'script' if job.mode == 'script' else 'post'}_result.json",
        }  # fmt: skip
        if fix == "continue" and sid:
            text = prompt("resume", **values)
        elif fix and sid:
            text = prompt("fix", error=fix.removeprefix("error: "), **values)
        elif rev.get("comment") and sid:
            text = prompt(f"{job.mode}_revise", **values)
        else:
            text = prompt(job.mode, **values)
            sid = None  # a fresh session
        resume = sid is not None
        if sid is None:
            sid = str(uuid.uuid4())
            self.store.set_session(job.run_id, job.mode, sid)  # stored first: a crash mid-run resumes it
        res = await self.claude.run(text, cwd=ep, log=logf, session_id=sid, resume=resume,
                                    add_dirs=[self.s.reels_dir])  # fmt: skip
        if res.session_id != sid:
            self.store.set_session(job.run_id, job.mode, res.session_id)
        return res.text, res.cost_usd

    def _collect(self, job: Job, ep: Path, since: float) -> Outcome:
        idea = job.inp.get("idea") or {}
        if job.mode == "script":
            r = read_result(ep, "script_result.json", ScriptResult, since - 5)
            script = {
                "meta": {"title": r.title, "hook": r.hook, "key_takeaway": r.takeaway, "duration_s": r.duration_s},
                "scenes": [
                    {"id": f"s{i + 1}", "title": s.title, "narration": s.narration} for i, s in enumerate(r.scenes)
                ],
                "path": r.script_path,
            }  # fmt: skip
            post = {"hook": r.hook, "summary": r.takeaway, "caption": r.caption, "hashtags": r.hashtags}
            return Outcome({"title": r.title, "scenario": {"script": script, "post": post}, "episode": str(ep)}, 0.0)
        r2 = read_result(ep, "post_result.json", PostResult, since - 5)
        video, cover = Path(r2.video), Path(r2.cover)
        key = f"{(self.s.blob_prefix or 'reels').strip('/')}/{job.run_id}/v{job.visit}-{int(time.time())}"
        vref = self._upload(f"{key}/{video.name}", video)
        cref = self._upload(f"{key}/{cover.name}", cover)
        variant = {
            "video": {"ref": vref, "duration_s": r2.duration_s, "size": video.stat().st_size, "path": str(video)},
            "cover": {"ref": cref, "path": str(cover)},
            "post": {"caption": r2.caption, "hashtags": [h.lstrip("#") for h in r2.hashtags]},
            "metadata": {"title": r2.title or idea.get("title", ""), "changed": r2.changed, "summary": r2.summary},
        }  # fmt: skip
        return Outcome({"title": r2.title, "variant": variant, "episode": str(ep)}, 0.0)

    def _upload(self, key: str, path: Path) -> str:
        if self.uploader is None:
            return path.resolve().as_uri()  # file:// for local tests
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return self.uploader.put_file(key, path, ctype)

    async def _usage_gate(self, ep: Path) -> None:
        while True:
            if time.time() - self.claude.usage.seen_at > PROBE_EVERY_S:
                await self.claude.probe(ep, self.s.log_dir / "probe.jsonl")
            bad = self.claude.usage.blocking(self.s.min_left)
            if bad is None:
                return
            name, w = bad
            left = max(0.0, 1 - w.utilization)
            await self.notify.send(f"⏸ {name} window: {left:.0%} left. Pausing until {_when(w.resets_at)}.")
            await self._sleep_until(w.resets_at)
            self.claude.usage.seen_at = 0.0  # re-probe after the reset

    def _next_reset(self) -> float:
        w = self.claude.usage.windows.get("five_hour")
        return w.resets_at if w and w.resets_at > time.time() else time.time() + 3600

    async def _sleep_until(self, ts: float) -> None:
        await self._sleep(max(60.0, ts - time.time() + RESET_SLACK_S))

    async def _complete(self, job: Job, output: dict[str, Any], cost: float | None) -> None:
        for i in range(5):  # the attempt may not be confirmed as waiting yet, or the broker reconnects
            try:
                await self.finisher.complete(job.handle, output, cost)
                return
            except Exception as e:  # noqa: BLE001
                log.warning("complete %s failed (%d): %r", job.step_key, i + 1, e)
                await self._sleep(15 * (i + 1))
        await self.notify.send(f"⚠️ {job.mode} for run {job.run_id[:8]} is ready but the core did not take it. "
                               "Retry the step: the stored result is returned at once.")  # fmt: skip

    async def _fail(self, job: Job, message: str, code: str) -> None:
        try:
            await self.finisher.fail(job.handle, message, code)
        except Exception:  # noqa: BLE001 - the attempt may be gone (cancelled run)
            log.exception("could not fail attempt %s", job.step_key)
