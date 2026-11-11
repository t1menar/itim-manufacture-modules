"""Artifact storage behind a Protocol; `LocalStore` serves tests and local runs, S3 comes as an adapter."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Ref:
    uri: str
    sha256: str
    size: int
    content_type: str

    def as_dict(self) -> dict[str, str | int]:
        return {"ref": self.uri, "sha256": self.sha256, "size": self.size, "content_type": self.content_type}


class StoreError(Exception):
    """The store could not take or give a file: transient for the platform."""


class ArtifactStore(Protocol):
    def put_file(self, key: str, path: Path, content_type: str) -> Ref: ...

    def put_bytes(self, key: str, data: bytes, content_type: str) -> Ref: ...

    def get_file(self, uri: str, dest: Path) -> None: ...


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _dest(self, key: str) -> Path:
        dest = (self.root / key).resolve()
        if not dest.is_relative_to(self.root.resolve()):
            raise ValueError(f"key escapes the store: {key!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest

    def put_file(self, key: str, path: Path, content_type: str) -> Ref:
        dest = self._dest(key)
        try:
            shutil.copyfile(path, dest)
        except OSError as exc:
            raise StoreError(f"cannot store {key}: {exc}") from exc
        return Ref(f"file://{dest}", sha256_file(dest), dest.stat().st_size, content_type)

    def put_bytes(self, key: str, data: bytes, content_type: str) -> Ref:
        dest = self._dest(key)
        try:
            dest.write_bytes(data)
        except OSError as exc:
            raise StoreError(f"cannot store {key}: {exc}") from exc
        return Ref(f"file://{dest}", hashlib.sha256(data).hexdigest(), len(data), content_type)

    def get_file(self, uri: str, dest: Path) -> None:
        if not uri.startswith("file://"):
            raise ValueError(f"not a local ref: {uri!r}")
        shutil.copyfile(uri.removeprefix("file://"), dest)
