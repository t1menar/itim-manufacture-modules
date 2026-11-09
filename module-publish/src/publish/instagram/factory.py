"""Build Fake or Real Instagram client from bootstrap + module DB secrets."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from publish.bootstrap import BootstrapConfig, ConfigError
from publish.db import repo
from publish.db import secrets as secret_keys
from publish.db.secrets import get_secret
from publish.instagram.base import InstagramClient
from publish.instagram.fake import FakeInstagramClient
from publish.instagram.real import AccountAuth, RealInstagramClient


def build_instagram_client(
    config: BootstrapConfig,
    *,
    factory: async_sessionmaker[AsyncSession] | None = None,
    dry_run: bool = True,
) -> InstagramClient:
    """`core` vault / credential_ref is no longer used for Instagram tokens."""
    if config.instagram_mode != "real":
        return FakeInstagramClient(dry_run=dry_run)

    async def resolve(account_id: str) -> AccountAuth:
        ig_user_id = config.instagram_ig_user_id
        token = config.instagram_access_token
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
                # Prefer column access_token; ignore legacy settings.credential_ref.
                if acc.access_token and acc.access_token.strip():
                    token = acc.access_token.strip()
                if not token:
                    token = await get_secret(session, secret_keys.SECRET_INSTAGRAM_DEFAULT_TOKEN)
        if not ig_user_id:
            raise ConfigError(
                "Instagram ig_user_id missing: set platform_accounts.external_id or "
                "PUBLISH_INSTAGRAM_IG_USER_ID"
            )
        if not token:
            raise ConfigError(
                "Instagram access token missing: set platform_accounts.access_token "
                "(or module_secrets 'instagram.default_access_token' / "
                "PUBLISH_INSTAGRAM_ACCESS_TOKEN for dev)"
            )
        return AccountAuth(ig_user_id=str(ig_user_id), access_token=token)

    return RealInstagramClient(
        resolve_account=resolve,
        graph_base=config.instagram_graph_base,
        api_version=config.instagram_api_version,
    )
