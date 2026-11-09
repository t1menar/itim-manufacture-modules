"""Executes one run: credential check, steps with cache and resume, result or fail callback.

Design rules (05 sections 6 to 9):
- Every state that must survive a crash is written to the database before it is acted on: the
  final result or error is stored BEFORE its callback is sent, so a restart re-sends it.
- Steps are skipped on resume when a `succeeded` or `reused` row exists.
- Cancellation and lease loss are signalled through events watched by the step race; a cancelled
  run sends no callback.
- A process kill (task cancellation) is never turned into a failure: the lease expires and the
  run is resumed by whoever claims it next.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import inspect
import json
import time
import uuid
from collections.abc import Callable
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mvideo.contract import JobInput, StageOutput
from mvideo.core_client import (
    CoreGateway,
    CoreRejected,
    CoreUnavailable,
    Credential,
    CredentialError,
    JobCall,
)
from mvideo.db import repo
from mvideo.db.models import ACTIVE_RUN_STATUSES, Run
from mvideo.ideas import repo as idea_repo
from mvideo.pipeline.budget import check_agent_run_gate
from mvideo.pipeline.context import RunContext
from mvideo.pipeline.errors import LeaseLost, RunCancelled, StepError
from mvideo.pipeline.state import check_run_transition
from mvideo.pipeline.steps.base import Step
from mvideo.settings_model import VideoSettings
from mvideo.storage import Artifact, Storage, StorageError

log = structlog.get_logger()

DEADLINE_MARGIN_S = 60
RENEW_TOKEN_MESSAGE = (
    "An admin must renew the Claude token (run claude setup-token and update the credential)"  # noqa: S105
)
EXPECTED_KIND = {"subscription": "claude_oauth_token", "api_key": "anthropic_api_key"}

Finalize = Callable[[RunContext], Any]  # sync or async: returns (output, artifacts)


class AuthState:
    """Whether the Claude credential was usable the last time a job fetched it (for GET /ready)."""

    def __init__(self) -> None:
        self.value = "missing"

    async def status(self) -> str:
        return self.value


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def input_hash(spec: Step, ctx: RunContext) -> str:
    """sha256 over step name, version, model, the settings it depends on, the job input and the
    sha256 of every file produced by earlier steps (05 section 8)."""
    dumped = ctx.settings.model_dump(mode="json")  # sections are models or dicts of models
    upstream = sorted(a.sha256 for files in ctx.outputs.values() for a in files.values())
    payload = {
        "step": spec.name,
        "version": spec.version,
        "model": ctx.settings.models.get(spec.name, ctx.settings.model),  # type: ignore[call-overload]
        "settings": {k: dumped[k] for k in spec.settings_keys},
        "input": ctx.input.model_dump(mode="json", exclude={"upstream"}),
        "idea": hashlib.sha256(json.dumps(ctx.idea, sort_keys=True).encode()).hexdigest(),
        "upstream": upstream,
        # an edited or re-activated prompt must not hit the step cache
        "prompts": sorted(
            f"{k}:{v.sha256}" for k, v in ctx.prompt_cache.items() if k in (spec.name, "skill")
        ),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _artifacts(outputs: dict[str, Any]) -> dict[str, Artifact]:
    return {name: Artifact(**meta) for name, meta in outputs.items()}


class Runner:
    def __init__(
        self,
        *,
        factory: async_sessionmaker[AsyncSession],
        storage: Storage,
        core: CoreGateway,
        steps: list[Step],
        finalize: Finalize,
        owner: str,
        auth_state: AuthState | None = None,
        lease_ttl_s: int = 60,
        lease_renew_s: float = 20.0,
        cancel_poll_s: float = 2.0,
        clock: Callable[[], dt.datetime] = _utcnow,
        services: dict[str, Any] | None = None,
        revise_steps: list[Step] | None = None,
    ) -> None:
        self._revise_steps = revise_steps  # None: revise runs the same steps (fakes)
        self._services = services or {}  # launcher, source, docker, ... for RunContext
        self._factory = factory
        self._storage = storage
        self._core = core
        self._steps = steps
        self._finalize = finalize
        self.owner = owner
        self.auth_state = auth_state or AuthState()
        self._ttl = lease_ttl_s
        self._renew = lease_renew_s
        self._poll = min(cancel_poll_s, lease_renew_s)
        self._clock = clock
        self._cancel_events: dict[uuid.UUID, asyncio.Event] = {}

    # ---- entry point ---------------------------------------------------------------------

    def signal_cancel(self, run_id: uuid.UUID) -> None:
        """Wake the run immediately when it is executing in this process."""
        event = self._cancel_events.get(run_id)
        if event is not None:
            event.set()

    async def execute(self, run_id: uuid.UUID) -> None:
        async with self._factory() as s:
            run = await repo.get_run(s, run_id)
        if run is None:
            return
        structlog.contextvars.bind_contextvars(
            run_id=str(run.id), job_id=str(run.job_id), production_id=str(run.production_id)
        )
        cancel, lost = asyncio.Event(), asyncio.Event()
        self._cancel_events[run_id] = cancel
        supervisor = asyncio.create_task(self._supervise(run_id, cancel, lost))
        try:
            await self._drive(run, cancel, lost)
        except RunCancelled:
            await self._finish(run_id, "cancelled")
            log.info("run_cancelled")
        except LeaseLost:
            log.warning("lease_lost_stopping")
        finally:
            self._cancel_events.pop(run_id, None)
            supervisor.cancel()
            await asyncio.gather(supervisor, return_exceptions=True)
            structlog.contextvars.clear_contextvars()

    # ---- supervision: cancel flag and lease renewal ---------------------------------------

    async def _supervise(self, run_id: uuid.UUID, cancel: asyncio.Event, lost: asyncio.Event) -> None:
        last_renew = time.monotonic()
        while True:
            await asyncio.sleep(self._poll)
            try:
                async with self._factory() as s, s.begin():
                    run = await repo.get_run(s, run_id)
                    if run is None or run.status not in ACTIVE_RUN_STATUSES:
                        return
                    if run.cancel_requested:
                        cancel.set()
                    if time.monotonic() - last_renew >= self._renew:
                        if not await repo.renew_lease(
                            s, run_id, self.owner, ttl_s=self._ttl, now=self._clock()
                        ):
                            lost.set()
                            return
                        last_renew = time.monotonic()
            except Exception:
                log.exception("supervise_failed")

    @staticmethod
    def _check_control(cancel: asyncio.Event, lost: asyncio.Event) -> None:
        if lost.is_set():
            raise LeaseLost
        if cancel.is_set():
            raise RunCancelled

    # ---- the run ---------------------------------------------------------------------------

    async def _drive(self, run: Run, cancel: asyncio.Event, lost: asyncio.Event) -> None:
        call = JobCall(
            job_id=str(run.job_id),
            production_id=str(run.production_id),
            base_url=(run.callback_base_url or "").rstrip("/"),
            traceparent=run.traceparent,
        )
        if run.cancel_requested or run.status == "cancelling":
            raise RunCancelled
        # Resume paths: the outcome is already decided and only its callback is missing.
        if run.result is not None:
            await self._send_result(run, call, run.result)
            return
        if run.error is not None:
            await self._send_fail(run, call, run.error)
            return

        settings = VideoSettings.model_validate(run.settings)
        ctx = RunContext(
            run_id=run.id,
            job_id=run.job_id,
            attempt=run.attempt,
            production_id=run.production_id,
            mode=run.mode,
            input=JobInput.model_validate(run.input),
            settings=settings,
            storage=self._storage,
            **self._services,
        )
        try:
            ctx.idea = await self._load_idea(ctx)
            ctx.credential = await self._fetch_credential(call, settings)
            await self._run_steps(run, ctx, call, cancel, lost)
            body = await self._build_result(run.id, ctx)
        except (RunCancelled, LeaseLost, asyncio.CancelledError):
            raise
        except StepError as exc:
            await self._fail(run, call, exc)
            return
        except StorageError as exc:
            await self._fail(run, call, StepError("transient", "s3_unavailable", str(exc)))
            return
        except Exception as exc:
            error_id = uuid.uuid4().hex[:12]
            log.exception("unexpected_error", error_id=error_id)
            await self._fail(
                run,
                call,
                StepError(
                    "fatal",
                    "internal",
                    f"unexpected error {type(exc).__name__}",
                    details={"error_id": error_id},
                ),
            )
            return
        await self._send_result(run, call, body)

    async def _load_idea(self, ctx: RunContext) -> dict[str, Any]:
        """The idea document of `input.idea_ref` from this module's database (D21)."""
        ref = ctx.input.idea_ref
        async with self._factory() as s:
            doc = await idea_repo.load_document(s, ref.id, ref.rev)
        if doc is None:
            raise StepError("fatal", "input_invalid", f"idea idea:{ref.id}:v{ref.rev} not found")
        return doc

    async def _fetch_credential(self, call: JobCall, settings: VideoSettings) -> Credential:
        ref = settings.agent.auth.credential_ref
        mode = settings.agent.auth.mode
        try:
            credential = await self._core.get_credential(call, ref)
        except CredentialError as exc:
            self.auth_state.value = "missing"
            raise StepError(
                "blocked", "agent_auth_failed", RENEW_TOKEN_MESSAGE, details={"reason": exc.reason}
            ) from exc
        except CoreUnavailable as exc:
            raise StepError("transient", "core_unavailable", str(exc)) from exc
        if credential.kind != EXPECTED_KIND[mode]:
            self.auth_state.value = "missing"
            raise StepError(
                "blocked",
                "agent_auth_failed",
                f"credential kind {credential.kind} does not match agent.auth.mode {mode}. "
                + RENEW_TOKEN_MESSAGE,
            )
        self.auth_state.value = "configured"
        return credential

    async def _run_steps(
        self, run: Run, ctx: RunContext, call: JobCall, cancel: asyncio.Event, lost: asyncio.Event
    ) -> None:
        async with self._factory() as s:
            existing = {}
            for row in await repo.list_steps(s, run.id):
                if row.name not in existing or row.try_ > existing[row.name].try_:
                    existing[row.name] = row
        limits = ctx.settings.limits
        if ctx.mode == "revise":
            await self._load_previous(run, ctx)

        for spec in self._revise_steps if ctx.mode == "revise" and self._revise_steps else self._steps:
            self._check_control(cancel, lost)
            row = existing.get(spec.name)
            if row is not None and row.status in ("succeeded", "reused"):
                ctx.outputs[spec.name] = _artifacts(row.outputs)  # resume: already done
                continue
            if self._clock() >= run.deadline - dt.timedelta(seconds=DEADLINE_MARGIN_S):
                raise StepError("transient", "deadline", "job deadline reached", step=spec.name)

            await spec.prepare(ctx)
            digest = input_hash(spec, ctx)
            async with self._factory() as s, s.begin():
                hit = await repo.find_reusable_step(s, spec.name, digest)
                if hit is not None:
                    now = self._clock()
                    await repo.upsert_step(
                        s, run.id, spec.name, 1, input_hash=digest, status="reused", reused_from=hit.id,
                        outputs=hit.outputs, started_at=now, finished_at=now, duration_s=0.0,
                    )  # fmt: skip
                    await repo.update_progress(s, run.id, step=spec.name, percent=spec.hi)
                    ctx.outputs[spec.name] = _artifacts(hit.outputs)
                    log.info("step_reused", step=spec.name, reused_from=str(hit.id))
                    continue
                if spec.uses_agent:
                    gate = await check_agent_run_gate(s, limits, self._clock())
                    if gate is not None:
                        raise gate.as_error(step=spec.name)

            started = self._clock()
            async with self._factory() as s, s.begin():
                await repo.upsert_step(
                    s, run.id, spec.name, 1, input_hash=digest, status="running", started_at=started,
                    finished_at=None, error=None, outputs={},
                )  # fmt: skip
                await repo.update_progress(s, run.id, step=spec.name, percent=spec.lo)
            await self._progress(call, spec.lo, spec.name, f"{spec.name} started")

            try:
                produced = await self._race(spec, ctx, cancel, lost)
            except StepError as exc:
                await self._mark_step_failed(run.id, spec, digest, exc)
                exc.step = exc.step or spec.name
                raise

            finished = self._clock()
            async with self._factory() as s, s.begin():
                await repo.upsert_step(
                    s, run.id, spec.name, 1, input_hash=digest, status="succeeded",
                    prompt_version=getattr(ctx.prompt_cache.get(spec.name), "version", None),
                    outputs={n: a.as_dict() for n, a in produced.items()}, finished_at=finished,
                    duration_s=(finished - started).total_seconds(),
                )  # fmt: skip
                await repo.update_progress(s, run.id, step=spec.name, percent=spec.hi)
                if spec.uses_agent:
                    await repo.log_usage(s, "agent_run", run.id, step=spec.name, at=finished)
            ctx.outputs[spec.name] = produced
            await self._progress(call, spec.hi, spec.name, f"{spec.name} finished")

    async def _load_previous(self, run: Run, ctx: RunContext) -> None:
        """Revise: files of the last succeeded run; analysis and research stay as they were."""
        async with self._factory() as s:
            prev = await repo.previous_outputs(s, run.production_id, run.id)
        need = ("analysis", "research", "capture", "package")
        if prev is None or any(n not in prev for n in need):
            raise StepError(
                "fatal", "input_invalid", "no succeeded previous run to revise", step="script-revise"
            )
        ctx.previous = {name: _artifacts(files) for name, files in prev.items()}
        if ctx.input.previous is None:
            raise StepError("fatal", "input_invalid", "revise needs input.previous", step="script-revise")
        ctx.previous["script"] = {"script.en.json": Artifact(ctx.input.previous.script_ref, "", 0, "json")}
        ctx.outputs["analysis"], ctx.outputs["research"] = ctx.previous["analysis"], ctx.previous["research"]

    async def _race(
        self, spec: Step, ctx: RunContext, cancel: asyncio.Event, lost: asyncio.Event
    ) -> dict[str, Artifact]:
        """Run the step, but stop it the moment the run is cancelled or its lease is lost."""
        task = asyncio.create_task(spec.run(ctx))
        watchers = [asyncio.create_task(cancel.wait()), asyncio.create_task(lost.wait())]
        try:
            done, _ = await asyncio.wait({task, *watchers}, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                return task.result()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise LeaseLost if lost.is_set() else RunCancelled
        finally:
            for w in watchers:
                w.cancel()
            if not task.done():
                task.cancel()  # the whole run is being torn down (process kill)

    async def _mark_step_failed(self, run_id: uuid.UUID, spec: Step, digest: str, exc: StepError) -> None:
        status = "blocked" if exc.error_class == "blocked" else "failed"
        async with self._factory() as s, s.begin():
            await repo.upsert_step(
                s, run_id, spec.name, 1, input_hash=digest, status=status,
                error={"class": exc.error_class, "code": exc.code, "message": exc.message},
                finished_at=self._clock(),
            )  # fmt: skip

    async def _progress(self, call: JobCall, percent: int, step: str, message: str) -> None:
        try:
            await self._core.progress(call, percent, step, message)
        except CoreRejected as exc:
            raise RunCancelled from exc  # the core dropped this job (cancelled or stale attempt)
        except Exception:
            log.warning("progress_not_delivered", step=step, percent=percent)

    # ---- outcome -----------------------------------------------------------------------------

    async def _build_result(self, run_id: uuid.UUID, ctx: RunContext) -> dict[str, Any]:
        built = self._finalize(ctx)
        output, artifacts = await built if inspect.isawaitable(built) else built
        StageOutput.model_validate(output)  # our own bug must not reach the core as a 422
        problems = await self._storage.verify(artifacts)
        if problems:
            raise StepError("transient", "s3_unavailable", f"files missing after upload: {problems}")
        async with self._factory() as s:
            run = await repo.get_run(s, run_id)
        if run is None:
            raise RuntimeError("run vanished")
        metrics: dict[str, Any] = {
            "cost_usd": float(run.cost_usd),
            "tokens_in": run.tokens_in,
            "tokens_out": run.tokens_out,
        }
        if ctx.settings.resolved_cost_mode() == "estimate":
            metrics["cost_estimated"] = True
        return {"output": output, "artifacts": [a.as_dict() for a in artifacts], "metrics": metrics}

    async def _send_result(self, run: Run, call: JobCall, body: dict[str, Any]) -> None:
        async with self._factory() as s, s.begin():
            await repo.store_outcome(s, run.id, result=body)  # persisted before it is sent
        try:
            await self._core.result(call, body)
        except CoreUnavailable:
            log.error("result_callback_undelivered_will_retry_after_restart")
            await self._release(run.id)
            return
        except CoreRejected:
            log.warning("result_callback_rejected_by_core")
        await self._finish(run.id, "succeeded")

    async def _fail(self, run: Run, call: JobCall, exc: StepError) -> None:
        log.warning("run_failed", error_class=exc.error_class, code=exc.code)
        await self._send_fail(run, call, exc.fail_body())

    async def _send_fail(self, run: Run, call: JobCall, body: dict[str, Any]) -> None:
        async with self._factory() as s, s.begin():
            await repo.store_outcome(s, run.id, error=body)
        try:
            await self._core.fail(call, body)
        except CoreUnavailable:
            log.error("fail_callback_undelivered_will_retry_after_restart")
            await self._release(run.id)
            return
        except CoreRejected:
            log.warning("fail_callback_rejected_by_core")
        await self._finish(run.id, "failed")

    async def _finish(self, run_id: uuid.UUID, status: str) -> None:
        async with self._factory() as s, s.begin():
            current = await repo.get_run(s, run_id)
            # cancelling -> cancelled is the only path that skips "running"
            if current is not None and current.status != status and status != "cancelled":
                check_run_transition(current.status if current.status != "accepted" else "running", status)
            await repo.finish_run(s, run_id, status, now=self._clock())

    async def _release(self, run_id: uuid.UUID) -> None:
        async with self._factory() as s, s.begin():
            await repo.release_lease(s, run_id, self.owner)
