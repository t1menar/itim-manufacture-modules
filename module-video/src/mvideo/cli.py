"""Entry point: `mvideo` starts the HTTP API; `mvideo validate DIR` checks step files."""

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


def validate_main(argv: list[str]) -> int:
    """`mvideo validate DIR [--src DIR] [--settings FILE]`: exit 0 when every file passes."""
    import argparse
    import json

    from mvideo.validate.rules import RuleConfig
    from mvideo.validate.runner import validate_dir
    from mvideo.validate.source import DirSource

    ap = argparse.ArgumentParser(prog="mvideo validate", description="Validate the JSON files of a video job")
    ap.add_argument("directory")
    ap.add_argument("--src", help="checked-out source tree used for line and citation checks")
    ap.add_argument("--flat-src", action="store_true", help="find source files by base name")
    ap.add_argument("--settings", help="settings values JSON (default: built-in defaults)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)
    values = json.loads(open(args.settings, encoding="utf-8").read()) if args.settings else None  # noqa: SIM115
    report = validate_dir(
        args.directory,
        source=DirSource(args.src, flat=args.flat_src) if args.src else None,
        cfg=RuleConfig.from_settings(values),
    )
    if args.json:
        sys.stdout.write(
            json.dumps(
                {"ok": report.ok, "checked": report.checked, "issues": [i.as_dict() for i in report.issues]},
                indent=1,
            )
            + "\n"
        )
    else:
        for issue in report.issues:
            sys.stdout.write(f"{issue}\n")
        sys.stdout.write(
            f"{'OK' if report.ok else 'FAILED'}: {len(report.checked)} files, {len(report.issues)} issues\n"
        )
    return 0 if report.ok else 1


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "validate":
        raise SystemExit(validate_main(sys.argv[2:]))
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
