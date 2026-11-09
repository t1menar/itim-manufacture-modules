"""D21: idea documents by ref, the scheduler and outbox, the status consumer, shared schemas."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from mvideo.db.engine import session_factory
from mvideo.db.models import AmqpInbox, Idea, IdeaOutbox, IdeaRevision, Topic
from mvideo.ideas import ids, relay, repo, scheduler, status
from mvideo.ideas.document import SCHEMA_DIR, build_document, idea_text, schema_errors
from mvideo.ideas.runtime import IdeaRuntime
from mvideo.ideas.scheduler import SchedulerParams
from tests import refdata
from tests.helpers import seed_idea

NOW = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)
PROD = uuid.UUID("0193a1b0-0000-7000-8000-000000000001")


@pytest.fixture
def factory(engine: AsyncEngine) -> Any:
    return session_factory(engine)


async def queue(factory: Any, idea_id: int, **kw: Any) -> None:
    await seed_idea(factory, idea_id=idea_id, status="queued", title=f"Idea {idea_id}", **kw)
    async with factory() as s, s.begin():
        await s.execute(
            update(Idea).where(Idea.id == idea_id).values(queued_at=NOW + dt.timedelta(seconds=idea_id))
        )


async def row(factory: Any, idea_id: int) -> Idea:
    async with factory() as s:
        idea = await s.get(Idea, idea_id)
    assert idea is not None
    return idea


# ---- ids, schemas, document ---------------------------------------------------------------------


def test_refs_and_message_ids_follow_the_shared_rules() -> None:
    assert ids.format_ref(42, 3) == "idea:42:v3" and ids.parse_ref("idea:42:v3") == (42, 3)
    with pytest.raises(ValueError):
        ids.parse_ref("idea:x")
    assert ids.ready_message_id(42, 3) == uuid.uuid5(ids.MANUFACTURE_NS, "idea:42:v3")
    assert ids.ready_message_id(42, 3) != ids.ready_message_id(42, 4)
    assert ids.status_message_id(42, 3, "done", PROD) == uuid.uuid5(
        ids.MANUFACTURE_NS, f"idea:42:v3:done:{PROD}"
    )


def test_vendored_schemas_equal_the_shared_contracts() -> None:
    contracts = Path(__file__).resolve().parents[2] / "contracts"
    if not contracts.is_dir():
        pytest.skip("contracts/ is not next to module-video")
    for name, path in (
        ("idea", "idea.json"), ("topic", "topic.json"),
        ("idea.ready", "events/idea.ready.json"), ("idea.status", "events/idea.status.json"),
    ):  # fmt: skip
        assert json.loads((SCHEMA_DIR / f"{name}.json").read_text()) == json.loads(
            (contracts / path).read_text()
        )


def test_document_matches_the_idea_schema_and_text_carries_the_guidance() -> None:
    doc = refdata.idea_document(
        audience="backend developers", constraints={"duration_s": 120}, notes="No hype."
    )
    assert schema_errors("idea", doc) == []
    assert schema_errors("idea", {**doc, "title": ""})
    text = idea_text(doc)
    assert text.splitlines()[0] == doc["title"] and "Audience: backend developers" in text
    assert "duration_s=120" in text and "Notes: No hype." in text


async def test_build_document_uses_topic_tags_when_the_idea_has_none(factory: Any) -> None:
    await seed_idea(factory, idea_id=7, status="ready", title="Seven")
    async with factory() as s:
        idea, topic = await s.get(Idea, 7), None
        assert idea is not None
        topic = await s.get(Topic, idea.topic_id)
        assert topic is not None
        doc = build_document(idea, topic)
    assert doc["tags"] == ["postgresql"] and schema_errors("idea", doc) == []


# ---- loading by ref -----------------------------------------------------------------------------


async def test_load_by_ref_needs_a_frozen_revision(factory: Any) -> None:
    await seed_idea(factory, idea_id=1, rev=1, status="ready", title="Still editable")
    await seed_idea(factory, idea_id=2, rev=1, status="in_production", title="In production")
    async with factory() as s:
        async with s.begin():
            await s.execute(IdeaRevision.__table__.delete())  # no snapshots: only live rows count
        assert await repo.load_document(s, 1, 1) is None  # content may still change
        doc = await repo.load_document(s, 2, 1)
        assert doc is not None and doc["title"] == "In production"
        assert await repo.load_document(s, 2, 9) is None  # rev moved on without a snapshot
        assert await repo.load_document(s, 99, 1) is None


# ---- scheduler ----------------------------------------------------------------------------------


async def test_tick_dispatches_by_priority_then_queue_time_within_limits(factory: Any) -> None:
    await queue(factory, 1, priority=0)
    await queue(factory, 2, priority=50)
    await queue(factory, 3, priority=50)
    await queue(factory, 4, priority=0)
    sent = await scheduler.tick(factory, SchedulerParams(max_dispatch_per_tick=2, max_in_flight=3), NOW)
    assert sent == ["idea:2:v1", "idea:3:v1"]  # priority first, then queued_at
    sent = await scheduler.tick(factory, SchedulerParams(max_dispatch_per_tick=5, max_in_flight=3), NOW)
    assert sent == ["idea:1:v1"]  # 2 in flight, room for one
    assert await scheduler.tick(factory, SchedulerParams(max_in_flight=3), NOW) == []
    assert (await row(factory, 4)).status == "queued"


async def test_dispatch_writes_snapshot_and_a_valid_orchestration_only_outbox_row(factory: Any) -> None:
    await queue(factory, 5, priority=10, pipeline_id="video-only")
    assert await scheduler.tick(factory, SchedulerParams(), NOW) == ["idea:5:v1"]
    idea = await row(factory, 5)
    assert idea.status == "dispatched" and idea.last_message_id == ids.ready_message_id(5, 1)
    async with factory() as s:
        out = (await s.execute(select(IdeaOutbox))).scalar_one()
        snap = await s.get(IdeaRevision, (5, 1))
    env = out.envelope
    assert schema_errors("envelope", env) == [] and schema_errors("idea.ready", env["payload"]) == []
    assert env["payload"] == {
        "idea_ref": {"id": 5, "rev": 1},
        "language": "en",
        "pipeline_id": "video-only",
        "priority": 10,
    }
    assert env["producer"] == "module:video" and env["message_id"] == str(ids.ready_message_id(5, 1))
    assert "title" not in json.dumps(env)  # the idea body never leaves the module
    assert snap is not None and snap.document["title"] == "Idea 5"
    assert await scheduler.tick(factory, SchedulerParams(), NOW) == []  # one idea.ready per (id, rev)


async def test_paused_inactive_topic_and_invalid_ideas(factory: Any) -> None:
    await queue(factory, 6)
    assert await scheduler.tick(factory, SchedulerParams(paused=True), NOW) == []
    await queue(factory, 7, topic_code="retired", active_topic=False)
    await queue(factory, 8, language="ru")
    sent = await scheduler.tick(factory, SchedulerParams(max_dispatch_per_tick=9, max_in_flight=9), NOW)
    assert sent == ["idea:6:v1"]  # idea 7 waits (inactive topic)
    bad = await row(factory, 8)
    assert bad.status == "failed" and bad.failure and bad.failure["code"] == "idea_invalid"


# ---- relay --------------------------------------------------------------------------------------


class FakeBroker:
    def __init__(self, fail_on: int | None = None) -> None:
        self.sent: list[tuple[str, dict[str, Any], str]] = []
        self.fail_on = fail_on

    async def publish(self, routing_key: str, body: bytes, *, message_id: str, type_: str) -> None:
        if self.fail_on is not None and len(self.sent) + 1 == self.fail_on:
            self.fail_on = None
            raise ConnectionError("broker down")
        self.sent.append((routing_key, json.loads(body), message_id))


async def test_relay_publishes_each_row_once_and_resumes_after_an_error(factory: Any) -> None:
    for i in (10, 11, 12):
        await queue(factory, i)
    await scheduler.tick(factory, SchedulerParams(max_dispatch_per_tick=3, max_in_flight=9), NOW)
    broker = FakeBroker(fail_on=2)
    with pytest.raises(ConnectionError):
        await relay.relay_once(factory, broker)
    assert len(broker.sent) == 1  # the first row is marked, the failed one is not
    assert await relay.relay_once(factory, broker) == 2
    assert await relay.relay_once(factory, broker) == 0
    assert [k for k, _, _ in broker.sent] == ["idea.ready"] * 3
    assert len({m for _, _, m in broker.sent}) == 3
    assert all(env["message_id"] == mid for _, env, mid in broker.sent)


async def test_runtime_pass_dispatches_and_publishes(factory: Any) -> None:
    await queue(factory, 13)
    broker = FakeBroker()
    rt = IdeaRuntime(factory, broker, SchedulerParams())
    await rt._once()
    assert [env["payload"]["idea_ref"] for _, env, _ in broker.sent] == [{"id": 13, "rev": 1}]


# ---- reverse statuses ---------------------------------------------------------------------------


def status_msg(
    idea_id: int, rev: int, st: str, *, production: uuid.UUID = PROD, failure: Any = None
) -> bytes:
    return json.dumps({
        "message_id": str(ids.status_message_id(idea_id, rev, st, production)), "type": f"idea.{st}",
        "schema_version": 1, "occurred_at": NOW.isoformat(), "producer": "core",
        "production_id": str(production),
        "payload": {"idea_ref": {"id": idea_id, "rev": rev}, "production_id": str(production), "status": st,
                    "failure": failure},
    }).encode()  # fmt: skip


async def test_status_flow_is_applied_once_and_in_order(factory: Any) -> None:
    await seed_idea(factory, idea_id=20, status="dispatched")
    assert await status.process_message(factory, status_msg(20, 1, "in_production")) == "applied"
    assert await status.process_message(factory, status_msg(20, 1, "in_production")) == "duplicate"
    assert (await row(factory, 20)).status == "in_production"
    assert await status.process_message(factory, status_msg(20, 1, "done")) == "applied"
    assert (await row(factory, 20)).status == "done"
    # a late in_production (reordered delivery) must not move the idea back
    assert (
        await status.process_message(factory, status_msg(20, 1, "in_production", production=uuid.uuid4()))
        == "stale"
    )
    assert (await row(factory, 20)).status == "done"


async def test_failed_keeps_the_failure_and_a_new_revision_is_not_touched(factory: Any) -> None:
    await seed_idea(factory, idea_id=21, status="dispatched")
    failure = {"code": "no_route", "message": None}
    msg = status_msg(21, 1, "failed", production=uuid.UUID(int=0), failure=failure)
    assert await status.process_message(factory, msg) == "applied"
    idea = await row(factory, 21)
    assert idea.status == "failed" and idea.failure == failure
    await seed_idea(factory, idea_id=22, rev=2, status="dispatched")
    assert await status.process_message(factory, status_msg(22, 1, "done")) == "stale"  # old rev
    assert (await row(factory, 22)).status == "dispatched"


async def test_unknown_invalid_and_inbox_outcomes(factory: Any) -> None:
    assert await status.process_message(factory, status_msg(404, 1, "done")) == "unknown"
    assert await status.process_message(factory, b"not json") == "invalid"
    wrong = json.loads(status_msg(1, 1, "done"))
    wrong["type"] = "idea.failed"  # payload says done
    assert await status.process_message(factory, json.dumps(wrong).encode()) == "invalid"
    no_failure = json.loads(status_msg(1, 1, "failed", failure={"code": "x"}))
    no_failure["payload"]["failure"] = None  # failed needs a failure
    assert await status.process_message(factory, json.dumps(no_failure).encode()) == "invalid"
    async with factory() as s:
        outcomes = {r.outcome for r in (await s.execute(select(AmqpInbox))).scalars()}
    assert outcomes == {"unknown"}  # invalid messages are dropped before the inbox


# ---- job intake and the pipeline ---------------------------------------------------------------


async def test_job_for_an_unknown_idea_is_rejected_at_intake(
    engine: AsyncEngine, storage: Any, config: Any
) -> None:
    from tests.harness import build_harness
    from tests.helpers import job_request

    h = build_harness(engine, storage, config)
    async with h.client() as c:
        resp = await c.post("/v1/jobs", json=job_request(idea_ref={"id": 999, "rev": 1}))
    assert resp.status_code == 422 and resp.json()["code"] == "input_invalid"
    async with h.client() as c:  # an idea that is still being edited has no stable content either
        await seed_idea(h.factory, idea_id=30, status="ready")
        assert (await c.post("/v1/jobs", json=job_request(idea_ref={"id": 30, "rev": 1}))).status_code == 202


async def test_steps_read_the_loaded_document_and_provenance_records_it() -> None:
    import hashlib

    from mvideo.pipeline.steps.analysis import AnalysisStep
    from mvideo.pipeline.steps.media_steps import _provenance
    from tests.test_steps import make_ctx

    ctx = make_ctx(None)  # type: ignore[arg-type]
    inputs = await AnalysisStep().inputs(ctx)
    assert json.loads(inputs["idea.json"]) == ctx.idea
    assert (await AnalysisStep().values(ctx))["idea_text"].startswith(ctx.idea["title"])
    prov = _provenance(ctx)["idea"]
    assert prov["idea_ref"] == "idea:42:v1"
    assert prov["sha256"] == hashlib.sha256(json.dumps(ctx.idea, sort_keys=True).encode()).hexdigest()


def test_idea_settings_come_from_the_environment() -> None:
    from mvideo.config import BootstrapConfig, ConfigError

    base = {
        "VIDEO_DATABASE_URL": "postgresql://x", "VIDEO_LISTEN_ADDR": "0.0.0.0:8080", "MODULE_CORE_URL": "http://c",
        "MODULE_CORE_TOKEN": "t", "S3_ENDPOINT": "http://s", "S3_ACCESS_KEY": "a", "S3_SECRET_KEY": "b",
        "S3_BUCKET": "m", "DOCKER_HOST": "unix:///x", "VIDEO_AGENT_NETWORK": "n",
    }  # fmt: skip
    off = BootstrapConfig.from_env(base)
    assert off.amqp_url is None and (off.ideas_tick_s, off.ideas_max_dispatch, off.ideas_max_in_flight) == (
        5.0,
        5,
        3,
    )
    extra = {"MODULE_AMQP_URL": "amqp://g", "VIDEO_IDEAS_PAUSED": "true", "VIDEO_IDEAS_MAX_IN_FLIGHT": "1"}
    on = BootstrapConfig.from_env({**base, **extra, "MODULE_AMQP_PREFIX": "t1."})
    assert (
        on.amqp_url == "amqp://g"
        and on.ideas_paused
        and on.ideas_max_in_flight == 1
        and on.amqp_prefix == "t1."
    )
    assert "amqp://g" not in repr(on)
    with pytest.raises(ConfigError):
        BootstrapConfig.from_env({**base, "VIDEO_IDEAS_TICK_S": "soon"})
