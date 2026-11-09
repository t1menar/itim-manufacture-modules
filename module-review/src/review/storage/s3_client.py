"""Build StorageClient from module_secrets/settings with env-fallback mapping.

Callers must pass env_fallback from BootstrapConfig (only bootstrap reads os.environ).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from review.db import secrets as keys
from review.db.secrets import get_secret, get_setting
from review.observability.logging import get_logger

log = get_logger(__name__)

from mf_storage import StorageClient, StorageConfig, StorageError

__all__ = ["StorageClient", "StorageConfig", "StorageError", "load_storage_client"]


async def load_storage_client(
    session: AsyncSession,
    *,
    env_fallback: Mapping[str, str] | None = None,
) -> StorageClient | None:
    """Return StorageClient or None if S3 is not configured.

    DB secrets/settings win; `env_fallback` supplies S3_* keys from bootstrap only.
    """
    source = env_fallback or {}
    secrets_access = await get_secret(session, keys.SECRET_S3_ACCESS_KEY)
    secrets_secret = await get_secret(session, keys.SECRET_S3_SECRET_KEY)
    setting = await get_setting(session, keys.SETTING_S3)
    cfg_map: dict[str, Any] = dict(setting) if isinstance(setting, dict) else {}

    endpoint = str(cfg_map.get("endpoint") or "").strip() or (source.get("S3_ENDPOINT") or "").strip()
    access = (secrets_access or "").strip() or (source.get("S3_ACCESS_KEY") or "").strip()
    secret = (secrets_secret or "").strip() or (source.get("S3_SECRET_KEY") or "").strip()
    if not endpoint or not access or not secret:
        return None

    public = (
        str(cfg_map.get("public_endpoint") or "").strip()
        or (source.get("S3_PUBLIC_ENDPOINT") or "").strip()
        or None
    )
    bucket = str(cfg_map.get("bucket") or source.get("S3_BUCKET") or "manufacture").strip()
    secure = (
        bool(cfg_map["secure"])
        if "secure" in cfg_map
        else ((source.get("S3_SECURE") or "").strip().lower() in {"1", "true", "yes"})
    )
    if "public_secure" in cfg_map:
        public_secure: bool | None = bool(cfg_map["public_secure"])
    else:
        raw = (source.get("S3_PUBLIC_SECURE") or "").strip().lower()
        public_secure = None if not raw else raw in {"1", "true", "yes"}
    region = str(cfg_map.get("region") or source.get("S3_REGION") or "us-east-1").strip()

    config = StorageConfig(
        endpoint=endpoint.split("://", 1)[-1].rstrip("/"),
        access_key=access,
        secret_key=secret,
        bucket=bucket,
        secure=secure,
        public_endpoint=public.split("://", 1)[-1].rstrip("/") if public else None,
        public_secure=public_secure,
        region=region,
    )
    return StorageClient(config)
