"""Public HTTPS hosting for the files Meta downloads (`video_url`, `cover_url`)."""

from __future__ import annotations

import asyncio
import base64
import secrets
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


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
