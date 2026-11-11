"""Manufacture platform adapter: the `publish` step as an SDK module (`mf-module run mipub.adapter:app`).

Input is the approved variant of module-video-generation plus the account code. `step_key = <run_id>:<step>`; the
ledger (account + content hash) is what really prevents double posts, also across runs. An unknown outcome is
`attention`: an operator decides, nothing is resent.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from manufacture import Context, Fatal, Module, NeedsAttention, Transient
from pydantic import BaseModel, Field

from mipub.service import Confirm, PublishRequest, PublishService


class Media(BaseModel):
    ref: str
    sha256: str = ""


class PostIn(BaseModel):
    caption: str
    hashtags: list[str] = Field(default_factory=list)


class StepIn(BaseModel):
    idea_ref: str
    account: str
    video: Media
    cover: Media | None = None
    post: PostIn


class StepOut(BaseModel):
    external_post_id: str
    url: str
    published_at: str | None
    account: str


Provider = Callable[[], Awaitable[PublishService]]


def make_app(
    provider: Provider, confirm: Callable[[Context[Any]], Confirm | None] | None = None,
    name: str = "instagram-publisher", version: str = "0.1.0",
) -> Module[Any]:  # fmt: skip
    app = Module(name, version=version, concurrency=1)

    @app.step(input=StepIn, output=StepOut)
    async def handle(ctx: Context[Any], inp: StepIn) -> StepOut:
        svc = await provider()
        req = PublishRequest(
            idea_ref=inp.idea_ref, step_key=f"{ctx.run_id}:{ctx.step}", account=inp.account,
            video_uri=inp.video.ref, video_sha256=inp.video.sha256, caption=inp.post.caption,
            hashtags=inp.post.hashtags, cover_uri=inp.cover.ref if inp.cover else None,
        )  # fmt: skip
        await ctx.progress(0.1, "publishing")
        out = await svc.publish(req, confirm(ctx) if confirm else None)
        doc = out.document
        if out.status == "published":
            return StepOut(
                external_post_id=str(doc["external_post_id"]), url=str(doc["url"]),
                published_at=doc.get("published_at"), account=inp.account,
            )  # fmt: skip
        if out.attention:
            raise NeedsAttention(
                f"publish outcome is unknown for {inp.account}: check Instagram before retrying", code="unknown_outcome"
            )
        code, msg = str(doc.get("code", out.status)), str(doc.get("message", out.status))
        if out.retryable:
            raise Transient(msg, code=code, retry_after_s=60)
        raise Fatal(msg, code=code)

    return app


class EnvTokens:
    """Tokens from `MIPUB_TOKEN_<ACCOUNT CODE>` (the platform fills them from `secretRef`)."""

    async def token(self, account_code: str) -> str:
        key = "MIPUB_TOKEN_" + "".join(c if c.isalnum() else "_" for c in account_code.upper())
        value = os.environ.get(key)
        if not value:
            raise Fatal(f"secret {key} is not set", code="secret_missing")
        return value


async def file_loader(uri: str) -> bytes:
    if not uri.startswith("file://"):
        raise Fatal(f"unsupported media ref {uri!r}", code="media_ref_unsupported")
    return await asyncio.to_thread(Path(uri.removeprefix("file://")).read_bytes)


_service: PublishService | None = None


async def _from_env() -> PublishService:
    """Production wiring (`MIPUB_*`): Postgres, Graph API, MinIO presigned `video_url` (`S3_*`) or an SFTP web host."""
    global _service  # noqa: PLW0603
    if _service is None:
        from mipub.db import make_engine, make_sessionmaker  # noqa: PLC0415
        from mipub.graph import DEFAULT_API_VERSION, DEFAULT_GRAPH_BASE, GraphClient  # noqa: PLC0415
        from mipub.host import MediaHost, MinioHost, SftpHost  # noqa: PLC0415

        env = os.environ
        sm = make_sessionmaker(make_engine(env["MIPUB_DATABASE_URL"]))
        graph = GraphClient(
            graph_base=env.get("MIPUB_GRAPH_BASE", DEFAULT_GRAPH_BASE),
            api_version=env.get("MIPUB_API_VERSION", DEFAULT_API_VERSION),
        )
        host: MediaHost
        if env.get("S3_ENDPOINT"):
            from mf_storage.client import StorageClient, StorageConfig  # noqa: PLC0415

            host = MinioHost(StorageClient(StorageConfig.from_mapping(dict(env))))
        else:
            host = SftpHost(
                env["MIPUB_HOST_TARGET"], env["MIPUB_HOST_DIR"], env["MIPUB_HOST_URL"],
                env["MIPUB_HOST_KEY_B64"], file_loader,
            )  # fmt: skip
        _service = PublishService(sm, graph, host, EnvTokens())
    return _service


app = make_app(_from_env)

__all__ = ["EnvTokens", "StepIn", "StepOut", "app", "file_loader", "make_app"]
