"""Shared MinIO/S3 helpers for Manufacture Python modules.

Parses `s3://bucket/key` artifact refs and issues short-lived HTTPS GET URLs.
Modules keep no domain logic here — only object storage plumbing.
"""

from __future__ import annotations

from mf_storage.client import StorageClient, StorageConfig, StorageError
from mf_storage.refs import ObjectRef, parse_s3_ref

__all__ = [
    "ObjectRef",
    "StorageClient",
    "StorageConfig",
    "StorageError",
    "parse_s3_ref",
]
