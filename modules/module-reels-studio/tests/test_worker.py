from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from mstudio.claude import Claude, parse_rate_event
from mstudio.episodes import new_episode_dir, series_name, slugify
from mstudio.notify import LogNotifier
from mstudio.settings import Settings, child_env
from mstudio.store import Job, Store
from mstudio.worker import Worker

FAKE = Path(__file__).with_name("fake_claude.py")
IDEA = {"title": "How Postgres reads pages", "playlists": ["postgres"], "description": "vision"}


class Finisher:
    def __init__(self) -> None:
        self.done: list[tuple[str, dict[str, Any], float | None]] = []
        self.failed: list[tuple[str, str, str]] = []

    async def complete(self, handle: str, output: dict[str, Any], cost_usd: float | None) -> None:
        self.done.append((handle, output, cost_usd))

    async def fail(self, handle: str, message: str, code: str) -> None:
        self.failed.append((handle, message, code))


class Uploader:
    def __init__(self) -> None:
        self.put: list[str] = []

    def put_file(self, key: str, path: Path, content_type: str) -> str:
        self.put.append(key)
        return f"s3://bucket/{key}"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    reels = tmp_path / "Reels"
    (reels / "Postgres" / "04-wal").mkdir(parents=True)
    plan = tmp_path / "plan.json"
    plan.write_text("[]")
    monkeypatch.setenv("FAKE_CLAUDE_PLAN", str(plan))
    monkeypatch.setenv("MTGR_BOT_TOKEN", "123:secret")
    s = Settings(reels_dir=reels, state_dir=tmp_path / "state", claude_bin=str(FAKE), tg_token="", tg_chats=())
    store = Store(s.db_path)
    slept: list[float] = []

    async def sleep(x: float) -> None:
        slept.append(x)

    fin, up, note = Finisher(), Uploader(), LogNotifier()
    w = Worker(s, store, Claude(s), note, fin, up, sleep=sleep)
    return {"s": s, "store": store, "w": w, "fin": fin, "up": up, "note": note, "plan": plan, "slept": slept}


def calls(plan: Path) -> list[dict[str, Any]]:
    f = Path(str(plan) + ".calls")
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def job(mode: str, key: str = "k1", **inp: Any) -> Job:
    return Job(key, "run-1", mode, 1, f"h-{key}", {"idea": IDEA, **inp})


async def test_script_then_video_then_revision(env: dict[str, Any]) -> None:
    store, w, fin = env["store"], env["w"], env["fin"]
    store.put(job("script"))
    await w.process(store.next_job())  # type: ignore[arg-type]
    handle, out, cost = fin.done[0]
    assert handle == "h-k1" and cost == 1.5
    ep = Path(out["episode"])
    assert ep.name == "05-how-postgres-reads-pages" and ep.parent.name == "Postgres"
    assert len(out["scenario"]["script"]["scenes"]) == 4
    assert store.get("k1").state == "done"  # type: ignore[union-attr]

    store.put(job("video", "k2", scenario=out["scenario"], episode=str(ep)))
    await w.process(store.next_job())  # type: ignore[arg-type]
    v = fin.done[1][1]["variant"]
    assert v["video"]["ref"].endswith("/v.mp4") and v["cover"]["ref"].endswith("/v_cover.png")
    assert v["post"]["hashtags"] == ["postgres", "backend"] and v["video"]["size"] == 1000

    # the reviewer rejects: the same video session is resumed with the comment
    store.put(
        Job("k3", "run-1", "video", 2, "h-k3", {"idea": IDEA, "revision": {"comment": "fix the caption", "round": 2}})
    )
    await w.process(store.next_job())  # type: ignore[arg-type]
    c = [x for x in calls(env["plan"]) if x["args"][1] != "Reply with OK."]
    assert "--resume" in c[-1]["args"] and "fix the caption" in c[-1]["args"][1]
    assert c[-1]["args"][c[-1]["args"].index("--resume") + 1] == store.session("run-1", "video")
    assert all(not x["env_secret"] for x in c)  # the bot token never reaches Claude Code
    assert all(x["cwd"] == str(ep) for x in c)


async def test_limit_mid_run_sleeps_and_resumes(env: dict[str, Any]) -> None:
    env["plan"].write_text(json.dumps(["limit", "ok"]))
    env["store"].put(job("script"))
    await env["w"].process(env["store"].next_job())
    assert env["fin"].done and env["slept"] and env["slept"][0] > 3000
    c = [x for x in calls(env["plan"]) if x["args"][1] != "Reply with OK."]
    assert "--resume" in c[1]["args"] and "paused by the usage limit" in c[1]["args"][1]
    assert any("Usage limit" in m for m in env["note"].sent)


async def test_restart_continues_the_interrupted_session(env: dict[str, Any]) -> None:
    env["plan"].write_text(json.dumps(["ok"]))
    store = env["store"]
    store.put(job("video"))
    store.set_state("k1", "running")
    store.set_session("run-1", "video", "11111111-1111-1111-1111-111111111111")
    await env["w"].process(store.next_job())
    c = [x for x in calls(env["plan"]) if x["args"][1] != "Reply with OK."]
    assert "--resume" in c[0]["args"] and "11111111-1111-1111-1111-111111111111" in c[0]["args"]
    assert "Do not start over" in c[0]["args"][1]
    assert any("resuming" in m for m in env["note"].sent)


async def test_low_usage_window_pauses_before_running(env: dict[str, Any]) -> None:
    w = env["w"]
    w.claude.usage.windows.update(
        parse_rate_event(
            {
                "rate_limit_info": {
                    "unifiedWindows": {"five_hour": {"utilization": 0.75, "resetsAt": 9e9, "status": "allowed"}}
                }
            }
        )
    )
    w.claude.usage.seen_at = 9e9
    env["store"].put(job("script"))
    await w.process(env["store"].next_job())
    assert env["slept"] and any("25% left" in m for m in env["note"].sent) and env["fin"].done


async def test_invalid_result_is_fixed_by_resuming(env: dict[str, Any]) -> None:
    env["plan"].write_text(json.dumps(["bad", "ok"]))
    env["store"].put(job("script"))
    await env["w"].process(env["store"].next_job())
    assert env["fin"].done and not env["slept"]
    c = [x for x in calls(env["plan"]) if x["args"][1] != "Reply with OK."]
    assert "ended with an error" in c[1]["args"][1] and "--resume" in c[1]["args"]


async def test_gives_up_after_rounds(env: dict[str, Any]) -> None:
    env["plan"].write_text(json.dumps(["crash"] * 20))
    env["store"].put(job("script"))
    await env["w"].process(env["store"].next_job())
    s = env["s"]
    assert env["fin"].failed and env["fin"].failed[0][2] == "studio_failed"
    assert len(env["slept"]) == s.max_rounds  # one wait for the reset per extra round
    assert env["store"].get("k1").state == "failed"  # type: ignore[union-attr]
    assert any("giving up" in m for m in env["note"].sent)


def test_child_env_strips_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("MTGR_BOT_TOKEN", "S3_SECRET_KEY", "MF_AMQP_URL", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("HOME_TEST_OK", "1")
    e = child_env()
    assert "HOME_TEST_OK" in e and not {
        "MTGR_BOT_TOKEN",
        "S3_SECRET_KEY",
        "MF_AMQP_URL",
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
    } & set(e)


def test_episode_naming(tmp_path: Path) -> None:
    (tmp_path / "AI" / "02-inside").mkdir(parents=True)
    assert series_name({"playlists": ["ai"]}, tmp_path) == "AI"
    assert series_name({"playlists": ["kafka"]}, tmp_path) == "Kafka"
    ep = new_episode_dir({"title": "Attention: how it works?", "playlists": ["AI"]}, tmp_path)
    assert ep.name == "03-attention-how-it-works" and (ep / "factory" / "idea.json").exists()
    assert slugify("Привет") == "episode"


def test_store_restart_resumes_running(tmp_path: Path) -> None:
    st = Store(tmp_path / "db")
    st.put(Job("a", "r", "script", 1, "h1", {}))
    st.put(Job("b", "r", "video", 1, "h2", {}))
    st.set_state("b", "running")
    assert Store(tmp_path / "db").next_job().step_key == "b"  # type: ignore[union-attr]
    st.put(Job("b", "r", "video", 1, "h3", {}))
    assert st.get("b").handle == "h3"  # type: ignore[union-attr]
    assert os.path.exists(tmp_path / "db")
