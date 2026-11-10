"""S3 (MinIO) storage: paths, upload with sha256, and verification before a result is announced."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aioboto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from mvideo.config import BootstrapConfig
from mvideo.observability.tracing import span


class StorageError(Exception):
    """S3 failed after retries (maps to transient s3_unavailable)."""


@dataclass(frozen=True, slots=True)
class Artifact:
    ref: str
    sha256: str
    size: int
    kind: str  # video | image | json | text

    def as_dict(self) -> dict[str, Any]:
        return {"ref": self.ref, "sha256": self.sha256, "size": self.size, "kind": self.kind}


def _hash_file(path: Path) -> tuple[str, int]:
    """sha256 and size of a file, read in 1 MiB chunks (run in a thread: it blocks)."""
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def object_key(production_id: str, attempt: int, step: str, name: str) -> str:
    """`<production_id>/video/<attempt>/<step>/<name>` (04 section 3.3)."""
    return f"{production_id}/video/{attempt}/{step}/{name}"


class Storage:
    def __init__(self, config: BootstrapConfig) -> None:
        self._bucket = config.s3_bucket
        self._session = aioboto3.Session()
        self._endpoint = config.s3_endpoint
        self._key = config.s3_access_key
        self._secret = config.s3_secret_key
        # botocore retries 5xx and connection errors itself (5 attempts, 05 section 7).
        self._cfg = Config(
            retries={"max_attempts": 5, "mode": "standard"},
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        )

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[Any]:
        async with self._session.client(
            "s3",
            endpoint_url=self._endpoint,
            aws_access_key_id=self._key,
            aws_secret_access_key=self._secret,
            region_name="us-east-1",
            config=self._cfg,
        ) as client:
            yield client

    def ref(self, key: str) -> str:
        return f"s3://{self._bucket}/{key}"

    def key_of(self, ref: str) -> str:
        prefix = f"s3://{self._bucket}/"
        if not ref.startswith(prefix):
            raise ValueError(f"not a reference into bucket {self._bucket}: {ref}")
        return ref[len(prefix) :]

    async def ready_check(self) -> str | None:
        """Readiness: the bucket answers. Returns a reason when it does not."""
        try:
            async with self._client() as s3:
                await s3.head_bucket(Bucket=self._bucket)
        except Exception:
            return "s3_unavailable"
        return None

    async def ensure_bucket(self) -> None:
        async with self._client() as s3:
            try:
                await s3.head_bucket(Bucket=self._bucket)
            except ClientError:
                await s3.create_bucket(Bucket=self._bucket)

    async def put_bytes(
        self, key: str, data: bytes, *, kind: str, content_type: str = "application/octet-stream"
    ) -> Artifact:
        digest = hashlib.sha256(data).hexdigest()
        try:
            with span("s3.upload", key=key, size=len(data)):
                async with self._client() as s3:
                    await s3.put_object(
                    Bucket=self._bucket, Key=key, Body=data, ContentType=content_type,
                    Metadata={"sha256": digest},
                )  # fmt: skip
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"upload of {key} failed: {exc}") from exc
        return Artifact(ref=self.ref(key), sha256=digest, size=len(data), kind=kind)

    async def put_file(
        self, key: str, path: Path, *, kind: str, content_type: str = "application/octet-stream"
    ) -> Artifact:
        """Streamed (multipart for large files) upload with the sha256 computed on the way."""
        digest, size = await asyncio.to_thread(_hash_file, path)
        try:
            with span("s3.upload", key=key, size=size):
                async with self._client() as s3:
                    await s3.upload_file(
                    str(path), self._bucket, key,
                    ExtraArgs={"ContentType": content_type, "Metadata": {"sha256": digest}},
                )  # fmt: skip
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"upload of {key} failed: {exc}") from exc
        return Artifact(ref=self.ref(key), sha256=digest, size=size, kind=kind)

    async def get_bytes(self, ref: str) -> bytes:
        try:
            async with self._client() as s3:
                obj = await s3.get_object(Bucket=self._bucket, Key=self.key_of(ref))
                body: bytes = await obj["Body"].read()
                return body
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"download of {ref} failed: {exc}") from exc

    async def head(self, ref: str) -> dict[str, Any]:
        """Size, content type and the stored sha256 of an object (for read-back checks)."""
        try:
            async with self._client() as s3:
                h = await s3.head_object(Bucket=self._bucket, Key=self.key_of(ref))
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"head of {ref} failed: {exc}") from exc
        return {
            "size": h["ContentLength"],
            "content_type": h.get("ContentType"),
            "sha256": (h.get("Metadata") or {}).get("sha256"),
        }

    async def verify(self, artifacts: list[Artifact]) -> list[str]:
        """Confirm every artifact exists with the announced size. Returns the refs that do not.

        Called before the result callback: the core would otherwise point at missing files.
        """
        problems: list[str] = []
        try:
            async with self._client() as s3:
                for art in artifacts:
                    try:
                        head = await s3.head_object(Bucket=self._bucket, Key=self.key_of(art.ref))
                    except ClientError:
                        problems.append(art.ref)
                        continue
                    if head["ContentLength"] != art.size:
                        problems.append(art.ref)
        except BotoCoreError as exc:
            raise StorageError(f"verification failed: {exc}") from exc
        return problems
