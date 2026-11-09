"""Entry point: `mvideo` starts the HTTP API."""

from __future__ import annotations

import sys

import uvicorn

from mvideo.app import create_app
from mvideo.config import BootstrapConfig, ConfigError
from mvideo.db.engine import create_engine
from mvideo.observability.logging import configure_logging


def main() -> None:
    try:
        config = BootstrapConfig.from_env()
    except ConfigError as exc:
        sys.stderr.write(f"mvideo: configuration error: {exc}\n")
        raise SystemExit(2) from exc
    configure_logging()
    app = create_app(config, engine=create_engine(config.database_url), migrate_on_start=True)
    uvicorn.run(app, host=config.host, port=config.port, log_config=None)


if __name__ == "__main__":
    main()
