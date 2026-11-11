"""`CaptureRunner` on Docker: runs the plan in a throw-away, network-less container."""

from __future__ import annotations

import asyncio
from typing import Any

import docker

from mvgen.sandbox.config import SandboxCatalog
from mvgen.sandbox.executor import make_client, run_capture


class DockerCaptureRunner:
    def __init__(self, catalog: SandboxCatalog, client: docker.DockerClient | None = None) -> None:
        self.catalog = catalog
        self._client = client

    async def run(self, plan: dict[str, Any], script: dict[str, Any], run_id: str) -> tuple[dict[str, Any], str]:
        def go() -> tuple[dict[str, Any], str]:
            client = self._client or make_client()
            return run_capture(client, self.catalog, plan, script, run_id=run_id)

        return await asyncio.to_thread(go)
