"""Instagram resolve prefers platform_accounts.access_token over env."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from publish.bootstrap import BootstrapConfig
from publish.instagram.factory import build_instagram_client


def _cfg(**kw: object) -> BootstrapConfig:
    return BootstrapConfig(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        listen_addr="127.0.0.1:8080",
        core_url="http://core",
        core_token="mft_x",
        instagram_mode="real",
        instagram_access_token=kw.get("env_token"),  # type: ignore[arg-type]
        instagram_ig_user_id=None,
    )


@pytest.mark.asyncio
async def test_resolve_uses_account_column() -> None:
    aid = uuid.uuid4()
    acc = MagicMock()
    acc.external_id = "178414000"
    acc.access_token = "ig-from-db"
    acc.settings = {}

    session = AsyncMock()
    session.get = AsyncMock(return_value=None)  # no module_secrets default needed

    # repo.get_platform_account patched via factory session
    factory = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    factory.return_value = ctx

    import publish.instagram.factory as fac

    original = fac.repo.get_platform_account
    fac.repo.get_platform_account = AsyncMock(return_value=acc)  # type: ignore[assignment]
    try:
        client = build_instagram_client(_cfg(env_token="env-ignored"), factory=factory)
        auth = await client._resolve(str(aid))  # type: ignore[attr-defined]
        assert auth.access_token == "ig-from-db"
        assert auth.ig_user_id == "178414000"
        assert "ig-from-db" not in repr(auth)
    finally:
        fac.repo.get_platform_account = original  # type: ignore[assignment]
