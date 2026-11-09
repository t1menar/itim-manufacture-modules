from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mvideo.config import BootstrapConfig
from mvideo.storage import Artifact, Storage, object_key


def test_object_key_layout() -> None:
    assert object_key("p1", 2, "render", "final.mp4") == "p1/video/2/render/final.mp4"


async def test_put_bytes_returns_hash_and_size(storage: Storage) -> None:
    art = await storage.put_bytes("t/a.json", b'{"a":1}', kind="json")
    assert art.ref == "s3://manufacture/t/a.json"
    assert art.sha256 == hashlib.sha256(b'{"a":1}').hexdigest()
    assert art.size == 7
    assert await storage.get_bytes(art.ref) == b'{"a":1}'


async def test_large_file_uploads_in_parts(storage: Storage, tmp_path: Path) -> None:
    path = tmp_path / "big.bin"
    data = b"x" * (12 * 1024 * 1024)
    path.write_bytes(data)
    art = await storage.put_file("t/big.bin", path, kind="video")
    assert art.size == len(data)
    assert art.sha256 == hashlib.sha256(data).hexdigest()
    assert await storage.verify([art]) == []


async def test_verify_reports_missing_and_wrong_size(storage: Storage) -> None:
    good = await storage.put_bytes("t/ok.txt", b"abc", kind="text")
    missing = Artifact(ref="s3://manufacture/t/nope.txt", sha256="0" * 64, size=1, kind="text")
    wrong = Artifact(ref=good.ref, sha256=good.sha256, size=999, kind="text")
    assert await storage.verify([good]) == []
    assert await storage.verify([good, missing, wrong]) == [missing.ref, wrong.ref]


async def test_ready_check(storage: Storage) -> None:
    assert await storage.ready_check() is None


def test_foreign_reference_is_rejected(env: dict[str, str]) -> None:
    store = Storage(BootstrapConfig.from_env(env))
    with pytest.raises(ValueError, match="not a reference"):
        store.key_of("s3://other-bucket/x")
