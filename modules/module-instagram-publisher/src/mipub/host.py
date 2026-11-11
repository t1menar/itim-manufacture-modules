"""Public HTTPS hosting for the files Meta downloads (`video_url`, `cover_url`)."""

from __future__ import annotations

import asyncio
import base64
import secrets
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mf_storage.client import StorageClient


class VideoHostError(Exception):
    pass


class MediaHost(Protocol):
    async def public_url(self, uri: str, ext: str) -> str:
        """A public https URL for the stored file `uri` (an https `uri` is returned as is)."""
        ...


@dataclass(frozen=True, slots=True)
class SftpHost:
    """Copies the file over SFTP (restricted key, one folder) to a web host that cleans old files itself."""

    target: str  # user@host
    remote_dir: str
    base_url: str
    key_b64: str = field(repr=False)
    load: Callable[[str], Awaitable[bytes]] = field(repr=False)

    async def public_url(self, uri: str, ext: str) -> str:
        if uri.startswith("https://"):
            return uri
        name = f"{secrets.token_urlsafe(18)}{ext}"
        data = await self.load(uri)
        with tempfile.TemporaryDirectory(prefix="vhost-") as tmp:
            d = Path(tmp)
            key = d / "key"
            key.write_bytes(base64.b64decode(self.key_b64))
            key.chmod(0o600)
            src = d / name
            src.write_bytes(data)
            batch = f"put {src} {self.remote_dir.rstrip('/')}/{name}\n"
            proc = await asyncio.create_subprocess_exec(
                "sftp", "-i", str(key), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={d / 'known_hosts'}",
                "-o", "ConnectTimeout=20", "-b", "-", self.target,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )  # fmt: skip
            _, err = await proc.communicate(batch.encode())
        if proc.returncode != 0:
            raise VideoHostError(f"sftp failed ({proc.returncode}): {err.decode(errors='replace')[-200:]}")
        return f"{self.base_url.rstrip('/')}/{name}"


@dataclass(frozen=True, slots=True)
class MinioHost:
    """`video_url`/`cover_url` are presigned GET URLs of the MinIO object, signed for the public endpoint.

    Meta downloads the file after `media` is created, so the URL must outlive container processing.
    """

    client: StorageClient
    ttl_s: int = 3 * 3600

    async def public_url(self, uri: str, ext: str) -> str:  # noqa: ARG002 - the object keeps its own name
        if uri.startswith("https://"):
            return uri
        try:
            return await asyncio.to_thread(self.client.resolve_https, uri, ttl_s=self.ttl_s, public=True)
        except Exception as exc:  # noqa: BLE001
            raise VideoHostError(f"cannot presign {uri}: {exc}") from exc
