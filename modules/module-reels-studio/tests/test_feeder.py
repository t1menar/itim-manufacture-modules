from __future__ import annotations

import json
from pathlib import Path

import httpx

from mstudio.feeder import IdeaClient, parse_idea, playlist_code, sync_file


def test_parse() -> None:
    assert parse_idea("Postgres | MVCC | show two versions | xmin") == ("Postgres", "MVCC", "show two versions | xmin")
    assert parse_idea("AI | Attention") == ("AI", "Attention", "")
    assert parse_idea("just text") is None
    assert playlist_code("System Design") == "system_design" and playlist_code("3D") == "s_3d"


async def test_sync_file_creates_queues_and_ticks(tmp_path: Path) -> None:
    seen: list[tuple[str, str, dict[str, object]]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content or b"{}")
        seen.append((req.method, req.url.path, body))
        if req.url.path in ("/v1/playlists", "/v1/environments", "/v1/rubrics"):
            return httpx.Response(409 if req.url.path == "/v1/playlists" else 200, json={})
        if req.url.path == "/v1/ideas":
            return httpx.Response(201, json={"id": 7})
        return httpx.Response(200, json={"id": 7})

    f = tmp_path / "IDEAS.md"
    f.write_text("# Ideas\n- [ ] Postgres | MVCC | two versions of a row\n- [x] AI | done (idea #1)\n- [ ] bad line\n")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        added = await sync_file(f, IdeaClient("http://idea", "t", client=c))
    assert added == [(7, "MVCC")]
    assert "- [x] Postgres | MVCC | two versions of a row (idea #7)" in f.read_text()
    assert ("POST", "/v1/ideas/7/status", {"status": "queued", "note": "from the owner"}) in seen
    ideas = [b for m, p, b in seen if p == "/v1/ideas"]
    assert ideas[0]["playlist_codes"] == ["postgres"] and ideas[0]["rubric_code"] == "reels"
    assert (
        ideas[0]["description"].startswith("MVCC. two versions of a row.") and len(ideas[0]["description"].split()) >= 8
    )


def test_env_file_like_compose(tmp_path: Path, monkeypatch: object) -> None:
    import os

    from mstudio.main import load_env_file

    f = tmp_path / ".env"
    f.write_text("A_X=1   # comment\nB_X='q # not a comment'  # c\nC_X=\"v\"\n# skip\nD_X=a#b\n")
    for k in ("A_X", "B_X", "C_X", "D_X"):
        os.environ.pop(k, None)
    load_env_file(f)
    assert [os.environ[k] for k in ("A_X", "B_X", "C_X", "D_X")] == ["1", "q # not a comment", "v", "a#b"]
