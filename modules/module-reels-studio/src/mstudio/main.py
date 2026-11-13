"""Entry point (`mstudio`): the Manufacture module plus the worker, in one process on the laptop.

Env: `MF_*` (broker, module name), `S3_*` (MinIO; `MSTUDIO_S3_ENDPOINT` overrides the endpoint seen from the laptop),
`MSTUDIO_*` (see settings.py), the Telegram bot token and owner ids of the review module.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

from mstudio.adapter import AppFinisher, make_app
from mstudio.claude import Claude
from mstudio.feeder import feed_forever
from mstudio.notify import LogNotifier, Notifier, TelegramNotifier
from mstudio.settings import Settings
from mstudio.store import Store
from mstudio.worker import Worker

log = logging.getLogger("mstudio")


class S3Uploader:
    def __init__(self) -> None:
        from mf_storage.client import StorageClient, StorageConfig  # noqa: PLC0415

        env = dict(os.environ)
        if env.get("MSTUDIO_S3_ENDPOINT"):
            env["S3_ENDPOINT"] = env["MSTUDIO_S3_ENDPOINT"]
        if env.get("MSTUDIO_S3_SECURE"):
            env["S3_SECURE"] = env["MSTUDIO_S3_SECURE"]
        self.client = StorageClient(StorageConfig.from_mapping(env, prefix="S3_"))

    def __repr__(self) -> str:
        return "S3Uploader()"

    def put_file(self, key: str, path: Path, content_type: str) -> str:
        uri = f"s3://{self.client.config.bucket}/{key.lstrip('/')}"
        return self.client.put_file(uri, str(path), content_type=content_type).uri


async def amain() -> None:
    s = Settings()
    store = Store(s.db_path)
    notifier: Notifier = TelegramNotifier(s.tg_token, s.tg_chats) if s.tg_token else LogNotifier()
    uploader = S3Uploader() if os.environ.get("S3_ENDPOINT") or os.environ.get("MSTUDIO_S3_ENDPOINT") else None
    worker: Worker | None = None

    def wake() -> None:
        if worker is not None:
            worker.wake.set()

    app = make_app(store, on_job=wake)
    worker = Worker(s, store, Claude(s), notifier, AppFinisher(app), uploader)

    async def run_worker() -> None:
        await asyncio.sleep(5)  # let the module come online before finishing attempts
        await worker.forever()

    tasks: list[asyncio.Task[Any]] = [asyncio.create_task(run_worker(), name="mstudio-worker")]
    if s.feed:
        tasks.append(asyncio.create_task(feed_forever(s.reels_dir / "IDEAS.md", notifier), name="mstudio-feeder"))
    try:
        await app.serve()
    finally:
        for t in tasks:
            t.cancel()


def load_env_file(path: Path) -> None:
    """KEY=VALUE lines of the stack's `deploy/.env` (values never printed); the process env wins."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if value[:1] in {"'", '"'} and value[0] in value[1:]:
            value = value[1 : value.index(value[0], 1)]
        else:  # docker compose: an unquoted value ends at " #"
            value = value.split(" #", 1)[0].split("\t#", 1)[0].strip()
        os.environ.setdefault(key, value)
    env = os.environ
    env.setdefault("MF_MODULE_NAME", "reels-studio")
    if "MF_AMQP_URL" not in env and env.get("RABBITMQ_USER"):
        host = env.get("MSTUDIO_AMQP_HOST", "127.0.0.1:5672")
        env["MF_AMQP_URL"] = f"amqp://{env['RABBITMQ_USER']}:{env.get('RABBITMQ_PASSWORD', '')}@{host}/"


def main() -> None:
    from manufacture._log import configure_logging  # noqa: PLC0415
    from manufacture.settings import RuntimeSettings  # noqa: PLC0415

    if len(sys.argv) > 1 and sys.argv[1] == "status":
        for j in Store(Settings().db_path).jobs():
            print(
                f"{j.state:8} {j.mode:6} run={j.run_id[:8]} visit={j.visit} attempts={j.attempts} {j.error or ''}"[:200]
            )
        return
    load_env_file(Path(os.environ.get("MSTUDIO_ENV_FILE", Path(__file__).parents[4] / "deploy" / ".env")))
    rs = RuntimeSettings()
    configure_logging(rs.log_format, rs.log_level)
    # httpx logs full request URLs at INFO, and Telegram URLs carry the bot token
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    asyncio.run(amain())


if __name__ == "__main__":
    main()
