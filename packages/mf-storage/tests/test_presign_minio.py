"""Integration against a real MinIO (local /tmp/mfinfra or CI service)."""

from __future__ import annotations

import os
import time
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from mf_storage import StorageClient, StorageConfig, StorageError

pytestmark = pytest.mark.skipif(
    not os.getenv("S3_ENDPOINT"),
    reason="S3_ENDPOINT not set (start deploy/scripts/mfinfra-minio.sh or CI MinIO)",
)


@pytest.fixture(scope="module")
def storage() -> StorageClient:
    cfg = StorageConfig.from_mapping(dict(os.environ))
    client = StorageClient(cfg)
    client.ensure_bucket()
    return client


def test_put_presign_download(storage: StorageClient) -> None:
    ref = "s3://manufacture/tests/presign/hello.txt"
    payload = b"manufacture-presign-ok"
    storage.put_bytes(ref, payload, content_type="text/plain")
    st = storage.stat(ref)
    assert st["size"] == len(payload)

    url = storage.presign_get(ref, ttl_s=120, public=True)
    assert url.startswith("http")
    with urlopen(url, timeout=10) as resp:  # noqa: S310 — local MinIO in tests
        assert resp.read() == payload
    assert "X-Amz-" in url or "Signature" in url


def test_ttl_floor(storage: StorageClient) -> None:
    ref = "s3://manufacture/tests/presign/ttl.txt"
    storage.put_bytes(ref, b"x", content_type="text/plain")
    with pytest.raises(StorageError, match="ttl_s"):
        storage.presign_get(ref, ttl_s=30, public=True)


def test_presign_expires_when_requested(storage: StorageClient) -> None:
    """Optional long test: set MF_STORAGE_TTL_WAIT=1 to wait past a 60s URL."""
    if os.getenv("MF_STORAGE_TTL_WAIT") != "1":
        pytest.skip("set MF_STORAGE_TTL_WAIT=1 to exercise real expiry")
    ref = "s3://manufacture/tests/presign/expire.txt"
    storage.put_bytes(ref, b"expire-me", content_type="text/plain")
    url = storage.presign_get(ref, ttl_s=60, public=True)
    with urlopen(url, timeout=10) as resp:  # noqa: S310
        assert resp.read() == b"expire-me"
    time.sleep(61)
    with pytest.raises(HTTPError):
        urlopen(url, timeout=10)  # noqa: S310


def test_resolve_https_passthrough(storage: StorageClient) -> None:
    assert storage.resolve_https("https://cdn.example/a.mp4") == "https://cdn.example/a.mp4"
    with pytest.raises(StorageError):
        storage.resolve_https("http://cdn.example/a.mp4")
