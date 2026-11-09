"""Source cache (03 section 5.5): pinned checkouts in named volumes, mounted read-only into agents.

A helper container (agent image, entrypoint `git`) clones with `--filter=blob:none --no-checkout`,
fetches the pinned commit at depth 1 and checks it out into the volume
`video-src-<sha256(url)[:12]>-<commit[:12]>`. The table `source_cache` tracks size and last use;
volumes beyond `sources.cache_max_gb` are removed least-recently-used first.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mvideo.db import repo
from mvideo.net.egress_proxy import start_listener
from mvideo.pipeline.errors import StepError
from mvideo.settings_model import AllowedRepo, VideoSettings

COMMIT = re.compile(r"^[0-9a-f]{40}$")


def volume_name(url: str, commit: str) -> str:
    return f"video-src-{hashlib.sha256(url.encode()).hexdigest()[:12]}-{commit[:12]}"


def check_allowed(url: str, repos: Sequence[AllowedRepo]) -> AllowedRepo:
    for r in repos:
        if r.url == url:
            return r
    raise StepError(
        "blocked", "source_not_allowed", f"{url} is not in sources.allowed_repos", step="analysis"
    )


def git_commands(url: str, commit: str) -> list[list[str]]:
    """The git argument lists run in order in /src (the helper's entrypoint is `git`)."""
    if not COMMIT.match(commit):
        raise ValueError(f"not a full commit id: {commit!r}")
    return [
        ["clone", "--filter=blob:none", "--no-checkout", url, "."],
        ["fetch", "--depth", "1", "origin", commit],
        ["checkout", "--detach", commit],
    ]


@dataclass(frozen=True, slots=True)
class CacheEntry:
    repo_url: str
    commit: str
    volume: str
    size_bytes: int
    last_used_s: float  # any monotonic ordering key: smaller is older


def plan_eviction(
    entries: Sequence[CacheEntry], max_bytes: int, keep: set[str] | None = None
) -> list[CacheEntry]:
    """Entries to remove, least recently used first, until the total fits `max_bytes`.

    Volumes in `keep` (in use by the current step) are never removed.
    """
    keep = keep or set()
    total = sum(e.size_bytes for e in entries)
    out: list[CacheEntry] = []
    for e in sorted(entries, key=lambda e: e.last_used_s):
        if total <= max_bytes:
            break
        if e.volume in keep:
            continue
        out.append(e)
        total -= e.size_bytes
    return out


class GitCache:
    def __init__(
        self, client: Any, sessions: async_sessionmaker[AsyncSession], image: str, network: str
    ) -> None:
        self.client, self.sessions, self.image, self.network = client, sessions, image, network

    def _clone_blocking(self, volume: str, url: str, commit: str, proxy_url: str) -> int:
        self.client.volumes.create(
            name=volume, labels={"manufacture.module": "video", "manufacture.kind": "src"}
        )
        script = " && ".join("git " + " ".join(c) for c in git_commands(url, commit))
        container = self.client.containers.run(
            self.image, ["sh", "-c", script + " && du -sk . | cut -f1"], entrypoint=[], detach=True,
            working_dir="/src", user="root", network=self.network, read_only=True, tmpfs={"/tmp": "size=64m"},
            environment={"HTTPS_PROXY": proxy_url, "https_proxy": proxy_url, "HOME": "/tmp"},
            volumes={volume: {"bind": "/src", "mode": "rw"}}, cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            labels={"manufacture.module": "video", "manufacture.purpose": "git"},
        )  # fmt: skip
        try:
            code = container.wait(timeout=900)["StatusCode"]
            out = container.logs().decode("utf-8", "replace")
            if code != 0:
                raise StepError("transient", "source_fetch_failed", out[-300:], step="analysis")
            return int(out.strip().splitlines()[-1]) * 1024
        finally:
            container.remove(force=True)

    async def ensure(
        self, settings: VideoSettings, url: str, commit: str, *, proxy_host: str = "module-video"
    ) -> str:
        """The volume holding `url` at `commit`; cloned when missing, `last_used_at` refreshed."""
        check_allowed(url, settings.sources.allowed_repos)
        volume = volume_name(url, commit)
        async with self.sessions() as s, s.begin():
            known = await repo.get_source(s, url, commit)
            if known is not None:
                await repo.touch_source(s, url, commit)
                return volume
        lo, hi = settings.network.proxy_ports
        listener = await start_listener(settings.network.allow_domains.get("sources", []), (lo, hi))
        try:
            size = await asyncio.to_thread(
                self._clone_blocking, volume, url, commit, f"http://{proxy_host}:{listener.port}"
            )
        finally:
            await listener.close()
        async with self.sessions() as s, s.begin():
            await repo.upsert_source(s, url, commit, volume, size)
        await self.evict(settings, keep={volume})
        return volume

    async def evict(self, settings: VideoSettings, keep: set[str] | None = None) -> list[str]:
        async with self.sessions() as s, s.begin():
            rows = await repo.list_sources(s)
            entries = [
                CacheEntry(r.repo_url, r.commit, r.volume, r.size_bytes, r.last_used_at.timestamp())
                for r in rows
            ]
            doomed = plan_eviction(entries, int(settings.sources.cache_max_gb * 1024**3), keep)
            for e in doomed:
                await repo.delete_source(s, e.repo_url, e.commit)
        for e in doomed:
            await asyncio.to_thread(self._remove_volume, e.volume)
        return [e.volume for e in doomed]

    def _remove_volume(self, name: str) -> None:
        with contextlib.suppress(Exception):  # already gone or in use; the next eviction retries
            self.client.volumes.get(name).remove(force=True)
