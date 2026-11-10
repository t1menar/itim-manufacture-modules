"""Put the video on a public HTTPS host so Meta can fetch it (`video_url`).

Meta's resumable upload takes only about 2 MiB per request, so a full reel goes through a small web
host instead: the file is copied there over SFTP (restricted key, one folder) and Meta is given the
https link. The host removes old files itself.
"""

from __future__ import annotations

import asyncio
import base64
import secrets
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


class VideoHostError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class VideoHost:
    target: str  # user@host
    remote_dir: str  # e.g. /var/www/reels
    base_url: str  # e.g. https://ziphy.ru/reels
    key_b64: str = field(repr=False)  # the private key, base64 of the PEM

    async def upload(self, data: bytes) -> str:
        name = f"{secrets.token_urlsafe(18)}.mp4"
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
