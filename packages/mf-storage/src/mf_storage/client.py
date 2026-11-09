"""MinIO client: put/get/head + presigned GET (internal vs public endpoint).

SigV4 signs the Host header. For Instagram/Telegram to fetch a file, the URL must be
signed for the **public** endpoint hostname (TLS reverse proxy), not `minio:9000`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import BinaryIO
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from mf_storage.refs import ObjectRef, parse_s3_ref


class StorageError(Exception):
    """Object storage failure (missing object, bad config, MinIO error)."""


@dataclass(frozen=True, slots=True)
class StorageConfig:
    """Bootstrap from env in each module; secrets never logged (repr hides keys)."""

    endpoint: str  # internal API host[:port], e.g. minio:9000 or 127.0.0.1:59000
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    bucket: str = "manufacture"
    secure: bool = False
    # Public host used when signing URLs for Instagram / Telegram / browsers.
    # If None, presign_public uses the same endpoint (local/dev only).
    public_endpoint: str | None = None
    public_secure: bool | None = None
    region: str = "us-east-1"

    @classmethod
    def from_mapping(cls, env: dict[str, str], *, prefix: str = "S3_") -> StorageConfig:
        endpoint = (env.get(f"{prefix}ENDPOINT") or "").strip()
        access = (env.get(f"{prefix}ACCESS_KEY") or "").strip()
        secret = (env.get(f"{prefix}SECRET_KEY") or "").strip()
        if not endpoint or not access or not secret:
            raise StorageError(f"missing {prefix}ENDPOINT / {prefix}ACCESS_KEY / {prefix}SECRET_KEY")
        bucket = (env.get(f"{prefix}BUCKET") or "manufacture").strip() or "manufacture"
        secure = (env.get(f"{prefix}SECURE") or "").strip().lower() in {"1", "true", "yes"}
        public = (env.get(f"{prefix}PUBLIC_ENDPOINT") or "").strip() or None
        public_secure_raw = (env.get(f"{prefix}PUBLIC_SECURE") or "").strip().lower()
        public_secure: bool | None = (
            None if not public_secure_raw else public_secure_raw in {"1", "true", "yes"}
        )
        region = (env.get(f"{prefix}REGION") or "us-east-1").strip() or "us-east-1"
        return cls(
            endpoint=_strip_scheme(endpoint),
            access_key=access,
            secret_key=secret,
            bucket=bucket,
            secure=secure,
            public_endpoint=_strip_scheme(public) if public else None,
            public_secure=public_secure,
            region=region,
        )


def _strip_scheme(endpoint: str) -> str:
    if "://" in endpoint:
        parsed = urlparse(endpoint)
        host = parsed.netloc or parsed.path
        return host.rstrip("/")
    return endpoint.rstrip("/")


class StorageClient:
    def __init__(self, config: StorageConfig) -> None:
        self.config = config
        self._internal = Minio(
            config.endpoint,
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=config.secure,
            region=config.region,
        )
        pub_host = config.public_endpoint or config.endpoint
        pub_secure = (
            config.public_secure
            if config.public_secure is not None
            else (True if config.public_endpoint else config.secure)
        )
        self._public = Minio(
            pub_host,
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=pub_secure,
            region=config.region,
        )

    def ensure_bucket(self, bucket: str | None = None) -> None:
        name = bucket or self.config.bucket
        if not self._internal.bucket_exists(name):
            self._internal.make_bucket(name)

    def put_bytes(
        self,
        ref: str | ObjectRef,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> ObjectRef:
        obj = self._as_ref(ref)
        from io import BytesIO

        self._internal.put_object(
            obj.bucket,
            obj.key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return obj

    def put_file(
        self,
        ref: str | ObjectRef,
        path: str,
        *,
        content_type: str = "application/octet-stream",
    ) -> ObjectRef:
        obj = self._as_ref(ref)
        self._internal.fput_object(obj.bucket, obj.key, path, content_type=content_type)
        return obj

    def put_stream(
        self,
        ref: str | ObjectRef,
        stream: BinaryIO,
        length: int,
        *,
        content_type: str = "application/octet-stream",
    ) -> ObjectRef:
        obj = self._as_ref(ref)
        self._internal.put_object(obj.bucket, obj.key, stream, length=length, content_type=content_type)
        return obj

    def stat(self, ref: str | ObjectRef) -> dict[str, object]:
        obj = self._as_ref(ref)
        try:
            st = self._internal.stat_object(obj.bucket, obj.key)
        except S3Error as exc:
            raise StorageError(f"stat failed for {obj.uri}: {exc.code}") from exc
        return {
            "size": st.size,
            "etag": st.etag,
            "content_type": st.content_type,
            "last_modified": st.last_modified,
        }

    def get_bytes(self, ref: str | ObjectRef) -> bytes:
        obj = self._as_ref(ref)
        try:
            resp = self._internal.get_object(obj.bucket, obj.key)
        except S3Error as exc:
            raise StorageError(f"get failed for {obj.uri}: {exc.code}") from exc
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def presign_get(
        self,
        ref: str | ObjectRef,
        *,
        ttl_s: int = 3600,
        public: bool = False,
    ) -> str:
        """Return a short-lived GET URL.

        `public=True` signs against `public_endpoint` (required for Instagram/Telegram fetch).
        """
        if ttl_s < 60:
            raise StorageError("ttl_s must be >= 60")
        if ttl_s > 7 * 24 * 3600:
            raise StorageError("ttl_s must be <= 7 days")
        obj = self._as_ref(ref)
        client = self._public if public else self._internal
        try:
            url = client.presigned_get_object(
                obj.bucket,
                obj.key,
                expires=dt.timedelta(seconds=ttl_s),
            )
        except S3Error as exc:
            raise StorageError(f"presign failed for {obj.uri}: {exc.code}") from exc
        return str(url)

    def resolve_https(
        self,
        ref: str,
        *,
        ttl_s: int = 3600,
        public: bool = True,
    ) -> str:
        """If `ref` is already https:// return as-is; if s3:// return a public presigned GET."""
        raw = (ref or "").strip()
        if raw.startswith("https://"):
            return raw
        if raw.startswith("http://"):
            raise StorageError("http:// artifact URLs are not accepted; use https:// or s3://")
        if raw.startswith("s3://"):
            return self.presign_get(raw, ttl_s=ttl_s, public=public)
        raise StorageError(f"unsupported artifact ref: {ref!r}")

    def _as_ref(self, ref: str | ObjectRef) -> ObjectRef:
        if isinstance(ref, ObjectRef):
            return ref
        return parse_s3_ref(ref, require_bucket=self.config.bucket)
