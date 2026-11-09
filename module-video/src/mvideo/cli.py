"""Entry point: `mvideo` starts the HTTP API."""

from __future__ import annotations

import sys

import uvicorn

from mvideo.app import create_app
from mvideo.config import BootstrapConfig, ConfigError
from mvideo.core_client import CoreClient
from mvideo.db.engine import create_engine
from mvideo.observability.logging import configure_logging
from mvideo.pipeline.steps.fake import fake_finalize, fake_pipeline
from mvideo.storage import Storage


def main() -> None:
    try:
        config = BootstrapConfig.from_env()
    except ConfigError as exc:
        sys.stderr.write(f"mvideo: configuration error: {exc}\n")
        raise SystemExit(2) from exc
    configure_logging()
    storage = Storage(config)
    app = create_app(
        config,
        engine=create_engine(config.database_url),
        migrate_on_start=True,
        storage=storage,
        core=CoreClient(config.core_url, config.core_token),
        # Fake steps until the real ones land (phases B4 to B8); they exercise the whole flow.
        steps=fake_pipeline(),
        finalize=fake_finalize,
        ready_checks=[storage.ready_check],
    )
    uvicorn.run(app, host=config.host, port=config.port, log_config=None)


if __name__ == "__main__":
    main()
