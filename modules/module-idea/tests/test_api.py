from __future__ import annotations

from httpx import AsyncClient

IDEA = {
    "title": "Seq scan beats index",
    "description": "Explain why a sequential scan can beat an index scan on a small table with a live demo",
    "key_takeaway": "Small tables are faster to scan than to index",
    "rubric_code": "race",
    "environment_code": "postgres17",
}


async def seed(c: AsyncClient) -> None:
    assert (await c.put("/v1/environments", json={"code": "postgres17", "title": "PG"})).status_code == 200
    assert (await c.put("/v1/rubrics", json={"code": "race", "title": "Race"})).status_code == 200


async def test_idea_lifecycle_over_http(client: AsyncClient) -> None:
    await seed(client)
    assert (await client.post("/v1/playlists", json={"code": "sql", "title": "SQL"})).status_code == 201
    r = await client.post("/v1/ideas", json=IDEA | {"playlist_codes": ["sql"]})
    assert r.status_code == 201
    idea_id = r.json()["id"]
    assert (await client.get("/v1/playlists/sql")).json()["idea_ids"] == [idea_id]
    r = await client.post(f"/v1/ideas/{idea_id}/status", json={"status": "queued"})
    assert r.status_code == 200 and r.json()["status"] == "queued"
    doc = (await client.get(f"/v1/ideas/{idea_id}/document")).json()
    assert doc["playlists"] == ["sql"]


async def test_not_ready_is_422_with_issues(client: AsyncClient) -> None:
    r = await client.post("/v1/ideas", json={"title": "x", "description": "short"})
    r = await client.post(f"/v1/ideas/{r.json()['id']}/status", json={"status": "queued"})
    assert r.status_code == 422 and len(r.json()["issues"]) == 4
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_unknown_fields_and_missing_things(client: AsyncClient) -> None:
    assert (await client.post("/v1/ideas", json=IDEA | {"bogus": 1})).status_code == 422
    assert (await client.get("/v1/ideas/999")).status_code == 404
    assert (await client.post("/v1/ideas", json=IDEA | {"rubric_code": "nope"})).status_code == 404
    assert (await client.get("/v1/stats", params={"group_by": "color"})).status_code == 422


async def test_bearer_token_is_enforced(sm) -> None:  # type: ignore[no-untyped-def]
    from httpx import ASGITransport

    from midea.app import create_app

    app = create_app(sessionmaker=sm, api_token="s3cret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/healthz")).status_code == 200
        assert (await c.get("/v1/ideas")).status_code == 401
        assert (await c.get("/v1/ideas", headers={"Authorization": "Bearer s3cret"})).status_code == 200
