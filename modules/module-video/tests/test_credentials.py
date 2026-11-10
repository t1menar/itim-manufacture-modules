"""Credentials kept in the module database: write-only API, local-first lookup, intake."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from mvideo.api.problems import ProblemError
from mvideo.app import create_app
from mvideo.config import BootstrapConfig
from mvideo.core_client import CredentialError, JobCall
from mvideo.credential_gateway import LocalCredentialGateway
from mvideo.db.engine import session_factory
from mvideo.intake import validate_job
from mvideo.settings_model import VideoSettings
from tests.harness import TOKEN
from tests.helpers import job_request

SECRET = "sk-ant-oat01-super-secret-value"
CALL = JobCall(job_id="j", production_id="p", base_url="http://core/x")


class FakeCore:
    async def progress(self, *a: object) -> None: ...
    async def result(self, *a: object) -> None: ...
    async def fail(self, *a: object) -> None: ...

    async def get_credential(self, call: JobCall, ref: str) -> object:
        raise CredentialError("not_found", ref)


async def test_api_stores_lists_without_values_and_deletes(
    config: BootstrapConfig, engine: AsyncEngine
) -> None:
    app = create_app(config, engine=engine)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t", headers=headers
    ) as c:
        body = {"kind": "claude_oauth_token", "value": SECRET, "note": "local"}
        assert (await c.put("/admin/v1/credentials/CLAUDE_OAUTH_TOKEN", json=body)).status_code == 201
        assert (await c.put("/admin/v1/credentials/CLAUDE_OAUTH_TOKEN", json=body)).status_code == 204
        listing = await c.get("/admin/v1/credentials")
        assert SECRET not in listing.text
        assert listing.json()[0]["ref"] == "CLAUDE_OAUTH_TOKEN" and listing.json()[0]["length"] == len(SECRET)
        bad = await c.put("/admin/v1/credentials/x", json={"kind": "nope", "value": SECRET})
        assert bad.status_code == 422 and SECRET not in bad.text
        lower = await c.put(
            "/admin/v1/credentials/cred:claude", json={"kind": "claude_oauth_token", "value": SECRET}
        )
        assert lower.status_code == 422
        assert (await c.delete("/admin/v1/credentials/CLAUDE_OAUTH_TOKEN")).status_code == 204
        assert (await c.delete("/admin/v1/credentials/CLAUDE_OAUTH_TOKEN")).status_code == 404


async def test_gateway_prefers_the_database_and_falls_back_to_core(
    config: BootstrapConfig, engine: AsyncEngine
) -> None:
    app = create_app(config, engine=engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as c:  # fmt: skip
        await c.put(
            "/admin/v1/credentials/CLAUDE_OAUTH_TOKEN", json={"kind": "claude_oauth_token", "value": SECRET}
        )
    gw = LocalCredentialGateway(FakeCore(), session_factory(engine))  # type: ignore[arg-type]
    cred = await gw.get_credential(CALL, "CLAUDE_OAUTH_TOKEN")
    assert (cred.kind, cred.value) == ("claude_oauth_token", SECRET) and SECRET not in repr(cred)
    try:
        await gw.get_credential(CALL, "other")
    except CredentialError as exc:
        assert exc.reason == "not_found"
    else:
        raise AssertionError("expected CredentialError")


def test_intake_accepts_a_locally_stored_credential_ref() -> None:
    raw = job_request(credentials=[])
    with pytest.raises(ProblemError) as err:
        validate_job(raw)
    assert err.value.status == 422
    ref = VideoSettings.model_validate(raw["settings"]["values"]).agent.auth.credential_ref
    assert validate_job(raw, frozenset({ref})).request.credentials == []
