"""CLI: publish serve | migrate | check-locale."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from publish.bootstrap import BootstrapConfig, ConfigError
from publish.observability.logging import configure_logging, get_logger


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="publish", description="Manufacture module-publish")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run HTTP API (+ optional AMQP consumer)")
    sub.add_parser("migrate", help="apply database migrations and exit")
    sub.add_parser("check-locale", help="validate i18n locale files")
    args = parser.parse_args(argv)

    configure_logging()
    log = get_logger("publish.cli")

    if args.cmd == "check-locale":
        from pathlib import Path

        locale = Path(__file__).resolve().parent / "i18n" / "locales" / "en.toml"
        if not locale.is_file():
            print(f"missing locale: {locale}", file=sys.stderr)
            raise SystemExit(1)
        # Phase 1: file presence only; full key check arrives with bot texts (phase 4/5).
        print(f"ok {locale}")
        return

    try:
        config = BootstrapConfig.from_env()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    if args.cmd == "migrate":
        from publish.db.migrate import upgrade_head

        upgrade_head(config.database_url)
        log.info("migrations_applied")
        return

    if args.cmd == "serve":
        from publish.app import create_app

        app = create_app(config, migrate_on_start=True, start_amqp=True)
        uvicorn.run(app, host=config.host, port=config.port, log_config=None)
        return


if __name__ == "__main__":
    main()
