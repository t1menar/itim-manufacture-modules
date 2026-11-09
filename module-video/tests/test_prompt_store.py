"""Runtime prompts in the database: seed, immutable versions, activation, admin API, step cache."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from mvideo.agents.prompts import PROMPTS_ROOT, PromptError, PromptStore, load_prompt
from mvideo.app import create_app
from mvideo.config import BootstrapConfig
from mvideo.db import prompts_repo
from mvideo.db.engine import session_factory
from mvideo.pipeline.runner import input_hash
from mvideo.pipeline.steps.analysis import AnalysisStep
from mvideo.pipeline.steps.media_steps import _provenance
from tests.harness import TOKEN
from tests.test_steps import make_ctx

STEPS = {"analysis", "research", "script", "capture", "package", "script-revise", "skill"}


@pytest.fixture
async def seeded(engine: AsyncEngine) -> Any:
    factory = session_factory(engine)
    async with factory() as s, s.begin():
        await prompts_repo.seed_from_files(s, PROMPTS_ROOT)
    return factory


async def test_seed_adds_packaged_versions_once_and_activates_them(engine: AsyncEngine) -> None:
    factory = session_factory(engine)
    async with factory() as s, s.begin():
        added = await prompts_repo.seed_from_files(s, PROMPTS_ROOT)
    assert {a.split("@")[0] for a in added} == STEPS
    async with factory() as s, s.begin():
        assert await prompts_repo.seed_from_files(s, PROMPTS_ROOT) == []
        active = {a.step: a.version for a in await prompts_repo.list_active(s)}
    assert active == dict.fromkeys(STEPS, "1.0.0")


async def test_store_reads_what_the_files_hold_and_resolves_active(seeded: Any) -> None:
    store = PromptStore(seeded)
    p = await store.get("script", "active")
    f = load_prompt("script", "1.0.0")
    assert (p.version, p.claude_md, p.task_md, p.sha256) == ("1.0.0", f.claude_md, f.task_md, f.sha256)
    assert (await store.get("skill", "active")).claude_md  # the skill is stored like a prompt
    with pytest.raises(PromptError):
        await store.get("script", "9.9.9")


async def test_new_version_is_immutable_validated_and_activated_with_a_revision(seeded: Any) -> None:
    store = PromptStore(seeded)
    base = load_prompt("package", "1.0.0")
    async with seeded() as s, s.begin():
        row = await prompts_repo.create_version(
            s, "package", "1.1.0", claude_md=base.claude_md + "\nBe brief.", task_md=base.task_md, actor="t"
        )
        assert row.sha256 != base.sha256
        with pytest.raises(prompts_repo.PromptConflict):  # versions never change
            await prompts_repo.create_version(s, "package", "1.1.0", claude_md="x", task_md=base.task_md)
        with pytest.raises(prompts_repo.PromptInvalid):  # a placeholder the step does not supply
            await prompts_repo.create_version(s, "package", "1.2.0", claude_md="x", task_md="{nope}")
        with pytest.raises(prompts_repo.PromptInvalid):
            await prompts_repo.create_version(s, "package", "v2", claude_md="x", task_md=base.task_md)
    assert (await store.get("package", "active")).version == "1.0.0"  # created, not activated
    async with seeded() as s, s.begin():
        with pytest.raises(prompts_repo.PromptConflict):  # stale If-Match
            await prompts_repo.activate(s, "package", "1.1.0", expected_revision=5)
        done = await prompts_repo.activate(s, "package", "1.1.0", expected_revision=1, actor="t")
    assert done.revision == 2
    assert (await store.get("package", "active")).claude_md.endswith("Be brief.")
    assert (await store.get("package", "1.0.0")).claude_md == base.claude_md  # pinned versions still work


async def test_editing_a_prompt_changes_the_step_hash(seeded: Any) -> None:
    ctx = make_ctx(None)  # type: ignore[arg-type]
    ctx.prompts = PromptStore(seeded)
    step = AnalysisStep()
    await step.prepare(ctx)
    before = input_hash(step, ctx)
    base = load_prompt("analysis", "1.0.0")
    async with seeded() as s, s.begin():
        await prompts_repo.create_version(
            s, "analysis", "1.0.1", claude_md=base.claude_md + "!", task_md=base.task_md
        )
        await prompts_repo.activate(s, "analysis", "1.0.1", expected_revision=1)
    ctx.prompt_cache.clear()
    await step.prepare(ctx)
    assert ctx.prompt_cache["analysis"].version == "1.0.1"
    assert input_hash(step, ctx) != before  # the step cache cannot serve the old prompt's result
    prov = _provenance(ctx)
    assert prov["prompts"]["analysis"] == "analysis@1.0.1"
    assert {
        "prompt_id": "analysis@1.0.1",
        "version": 10001,
        "sha256": ctx.prompt_cache["analysis"].sha256,
    } in prov["prompt_refs"]


def api(config: BootstrapConfig, engine: AsyncEngine) -> httpx.AsyncClient:
    app = create_app(config, engine=engine)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://m",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )


async def test_admin_api_lists_creates_and_activates(
    config: BootstrapConfig, engine: AsyncEngine, seeded: Any
) -> None:
    base = load_prompt("package", "1.0.0")
    async with api(config, engine) as c:
        listing = {p["step"]: p for p in (await c.get("/admin/v1/prompts")).json()}
        assert listing["package"]["versions"] == ["1.0.0"] and listing["package"]["default"] == "1.0.0"
        assert listing["package"]["revision"] == 1 and len(listing["package"]["sha256"]["1.0.0"]) == 64

        body = {
            "version": "1.1.0",
            "claude_md": base.claude_md + "\nmore",
            "task_md": base.task_md,
            "note": "tighter",
        }
        created = await c.post("/admin/v1/prompts/package", json=body)
        assert created.status_code == 201 and created.json()["claude_md"].endswith("more")
        assert (await c.post("/admin/v1/prompts/package", json=body)).status_code == 409
        bad = await c.post("/admin/v1/prompts/package", json={**body, "version": "1.2.0", "task_md": "{zzz}"})
        assert bad.status_code == 422

        assert (await c.put("/admin/v1/prompts/package/active", json={"version": "1.1.0"})).status_code == 428
        stale = await c.put(
            "/admin/v1/prompts/package/active", json={"version": "1.1.0"}, headers={"If-Match": "7"}
        )
        assert stale.status_code == 412
        ok = await c.put(
            "/admin/v1/prompts/package/active", json={"version": "1.1.0"}, headers={"If-Match": "1"}
        )
        assert ok.status_code == 200 and ok.json() == {"step": "package", "version": "1.1.0", "revision": 2}
        missing = await c.put(
            "/admin/v1/prompts/package/active", json={"version": "8.0.0"}, headers={"If-Match": "2"}
        )
        assert missing.status_code == 404

        one = await c.get("/admin/v1/prompts/package/1.1.0")
        assert one.json()["note"] == "tighter"
        audit = (await c.get("/admin/v1/prompts/audit")).json()
        assert [a["action"] for a in audit[:2]] == ["activate", "create"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(config, engine=engine)), base_url="http://m"
    ) as anon:
        assert (await anon.get("/admin/v1/prompts")).status_code == 401
