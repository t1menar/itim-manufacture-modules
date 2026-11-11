from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from mf_storage.client import StorageConfig

from mvgen.store import S3Store, StoreError


@dataclass
class FakeClient:
    config: StorageConfig
    objects: dict[str, bytes]
    fail: bool = False

    def put_bytes(self, ref: str, data: bytes, *, content_type: str = "") -> None:
        if self.fail:
            raise OSError("down")
        self.objects[ref] = data

    def put_file(self, ref: str, path: str, *, content_type: str = "") -> None:
        self.put_bytes(ref, Path(path).read_bytes())

    def get_bytes(self, ref: str) -> bytes:
        return self.objects[ref]


def make(fail: bool = False) -> tuple[S3Store, FakeClient]:
    c = FakeClient(StorageConfig("minio:9000", "a", "b", bucket="media"), {}, fail)
    return S3Store(c), c  # type: ignore[arg-type]


def test_put_and_get_roundtrip(tmp_path: Path) -> None:
    store, c = make()
    src = tmp_path / "v.mp4"
    src.write_bytes(b"video")
    ref = store.put_file("run1/final.mp4", src, "video/mp4")
    assert ref.uri == "s3://media/mvgen/run1/final.mp4" and ref.size == 5
    out = tmp_path / "out.mp4"
    store.get_file(ref.uri, out)
    assert out.read_bytes() == b"video"
    assert store.put_bytes("a/b.json", b"{}", "application/json").uri in c.objects


def test_errors_are_store_errors(tmp_path: Path) -> None:
    store, _ = make(fail=True)
    with pytest.raises(StoreError):
        store.put_bytes("k", b"x", "text/plain")
    with pytest.raises(ValueError):
        store.put_bytes("../x", b"x", "text/plain")
