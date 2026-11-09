"""Build Fake or Real Instagram client from bootstrap + DB/vault."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from publish.bootstrap import BootstrapConfig, ConfigError
from publish.clients.core import CoreClient
from publish.db import repo
from publish.instagram.base import InstagramClient
from publish.instagram.fake import FakeInstagramClient
from publish.instagram.real import AccountAuth, RealInstagramClient


def build_instagram_client(
    config: BootstrapConfig,
    *,
    factory: async_sessionmaker[AsyncSession] | None = None,
    core: CoreClient | None = None,
    dry_run: bool = True,
) -> InstagramClient:
    if config.instagram_mode != "real":
        return FakeInstagramClient(dry_run=dry_run)

    async def resolve(account_id: str) -> AccountAuth:
        ig_user_id = config.instagram_ig_user_id
        token = config.instagram_access_token
        settings: dict[str, Any] = {}
        if factory is not None:
            try:
                aid = uuid.UUID(account_id)
            except ValueError as exc:
                raise ConfigError(f"invalid platform_account_id {account_id!r}") from exc
            async with factory() as session:
                acc = await repo.get_platform_account(session, aid)
            if acc is None:
                raise ConfigError(f"unknown platform_account_id {account_id}")
            if acc.external_id:
                ig_user_id = acc.external_id
            settings = dict(acc.settings or {})
            cred_ref = settings.get("credential_ref") or settings.get("access_token_ref")
            if isinstance(cred_ref, str) and cred_ref.startswith("cred:") and core is not None:
                resp = await core.get_credential(cred_ref)
                if resp.status_code >= 300:
                    raise ConfigError(f"credential vault read failed for {cred_ref}")
                body = resp.json()
                value = body.get("value") if isinstance(body, dict) else None
                if not isinstance(value, str) or not value:
                    raise ConfigError(f"credential {cred_ref} empty")
                token = value
        if not ig_user_id:
            raise ConfigError(
                "Instagram ig_user_id missing: set platform_accounts.external_id or "
                "PUBLISH_INSTAGRAM_IG_USER_ID"
            )
        if not token:
            raise ConfigError(
                "Instagram access token missing: set PUBLISH_INSTAGRAM_ACCESS_TOKEN or "
                "account settings.credential_ref (Core credentials vault)"
            )
        return AccountAuth(ig_user_id=str(ig_user_id), access_token=token)

    return RealInstagramClient(
        resolve_account=resolve,
        graph_base=config.instagram_graph_base,
        api_version=config.instagram_api_version,
    )
