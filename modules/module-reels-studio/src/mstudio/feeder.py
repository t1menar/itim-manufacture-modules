"""Keeps the conveyor fed.

- **Ideas file** (`~/itim/Reels/IDEAS.md`): lines `- [ ] Series | Title | your vision` are created in the idea service,
  queued, and ticked off as `- [x] ... (idea #N)`. Telegram `/idea Series | Title | vision` does the same.
- **Trigger**: the core validates `trigger.schedule` but does not fire it yet, so every few minutes the feeder asks the
  core to poll the pipeline's source (`POST /api/v1/pipelines/<name>/runs` without data). The idea module starts the
  next queued idea only while nothing is in flight (`MIDEA_MAX_IN_FLIGHT=1`): the next video starts after a publish.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("mstudio.feeder")

LINE = re.compile(r"^(\s*[-*]\s*)\[ \]\s*(.+?)\s*$")


def parse_idea(text: str) -> tuple[str, str, str] | None:
    """`Series | Title | vision` → (series, title, vision); the vision may be empty, more `|` stay in it."""
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1], " | ".join(p for p in parts[2:] if p)


def playlist_code(series: str) -> str:
    """The idea service's code format: `^[a-z][a-z0-9_]{1,63}$`."""
    code = re.sub(r"[^a-z0-9]+", "_", series.lower()).strip("_")[:60] or "general"
    return code if code[0].isalpha() and len(code) > 1 else f"s_{code}"


class IdeaClient:
    def __init__(self, base: str, token: str = "", client: httpx.AsyncClient | None = None) -> None:
        self.base = base.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = client

    def __repr__(self) -> str:
        return f"IdeaClient({self.base})"

    async def _req(self, method: str, path: str, json: Any = None) -> httpx.Response:
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            return await c.request(method, f"{self.base}{path}", json=json, headers=self._headers)
        finally:
            if self._client is None:
                await c.aclose()

    async def add(self, series: str, title: str, vision: str) -> int:
        code = playlist_code(series)
        for path, body in setup_bodies(series, code):
            r = await self._req("PUT" if path != "/v1/playlists" else "POST", path, body)
            if r.status_code not in (200, 201, 409):  # 409: the playlist exists
                r.raise_for_status()
        r = await self._req("POST", "/v1/ideas", idea_body(series, title, vision, code))
        r.raise_for_status()
        idea_id = int(r.json()["id"])
        r = await self._req("POST", f"/v1/ideas/{idea_id}/status", {"status": "queued", "note": "from the owner"})
        r.raise_for_status()
        return idea_id


ENVIRONMENT = "mac_reels_studio"
RUBRIC = "reels"


def setup_bodies(series: str, code: str) -> list[tuple[str, dict[str, Any]]]:
    """The reference rows an idea needs before it may be queued (idempotent upserts)."""
    return [
        ("/v1/environments", {"code": ENVIRONMENT, "title": "Mac: Claude Code, Blender, Docker"}),
        ("/v1/rubrics", {"code": RUBRIC, "title": "Technical explainer Reel (~/itim/Reels/CLAUDE.md)"}),
        ("/v1/playlists", {"code": code, "title": series}),
    ]


def idea_body(series: str, title: str, vision: str, code: str) -> dict[str, Any]:
    description = f"{title}. {vision}".strip(" .") + "."
    if len(description.split()) < 8:
        description += f" A {series} explainer Reel for everyday backend developers."
    return {
        "title": title[:200], "description": description, "playlist_codes": [code], "tags": [code],
        "rubric_code": RUBRIC, "environment_code": ENVIRONMENT, "language": "en", "author": "owner",
        "key_takeaway": "Chosen by the studio from the author's vision.", "notes": f"series: {series}",
    }  # fmt: skip


async def sync_file(path: Path, ideas: IdeaClient) -> list[tuple[int, str]]:
    """Creates the unticked ideas of the file and ticks them. Returns (id, title) of the new ones."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    added: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = LINE.match(line)
        parsed = parse_idea(m.group(2)) if m else None
        if not m or not parsed:
            continue
        idea_id = await ideas.add(*parsed)
        lines[i] = f"{m.group(1)}[x] {m.group(2)} (idea #{idea_id})"
        added.append((idea_id, parsed[1]))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")  # after each one: no duplicates on a crash
    return added


async def trigger(core_url: str, token: str, pipeline: str) -> int:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{core_url.rstrip('/')}/api/v1/pipelines/{pipeline}/runs", json={},
            headers={"Authorization": f"Bearer {token}"},
        )  # fmt: skip
        return r.status_code


async def feed_forever(ideas_file: Path, notify: Any, every_s: float = 300.0) -> None:
    env = os.environ
    api = env.get("MSTUDIO_IDEA_URL", "http://127.0.0.1:8090")
    client = IdeaClient(api, env.get("MIDEA_API_TOKEN", ""))
    core, token = env.get("MSTUDIO_CORE_URL", "http://127.0.0.1:8080"), env.get("MF_ADMIN_TOKEN", "")
    pipeline = env.get("MSTUDIO_PIPELINE", "reels")
    while True:
        try:
            for idea_id, title in await sync_file(ideas_file, client):
                await notify.send(f"💡 Queued idea #{idea_id}: {title}")
        except Exception as e:  # noqa: BLE001
            log.warning("ideas file sync failed: %r", e)
        if token:
            try:
                code = await trigger(core, token, pipeline)
                if code >= 400:
                    log.warning("trigger %s: HTTP %s", pipeline, code)
            except httpx.HTTPError as e:
                log.warning("trigger failed: %s", type(e).__name__)
        await asyncio.sleep(every_s)
