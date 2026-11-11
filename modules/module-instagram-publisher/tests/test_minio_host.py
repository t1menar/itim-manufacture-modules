from __future__ import annotations

import pytest
from mf_storage.client import StorageClient, StorageConfig

from mipub.host import MinioHost


async def test_video_url_is_a_presigned_public_url() -> None:
    cfg = StorageConfig("minio:9000", "ak", "sk", bucket="media", public_endpoint="media.example.com")
    host = MinioHost(StorageClient(cfg))
    url = await host.public_url("s3://media/mvgen/r1/final.mp4", ".mp4")
    assert url.startswith("https://media.example.com/media/mvgen/r1/final.mp4?") and "X-Amz-Signature=" in url
    assert await host.public_url("https://cdn.example.com/a.mp4", ".mp4") == "https://cdn.example.com/a.mp4"
    with pytest.raises(Exception, match="presign"):
        await host.public_url("file:///x.mp4", ".mp4")
