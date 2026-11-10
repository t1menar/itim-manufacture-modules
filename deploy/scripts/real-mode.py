#!/usr/bin/env python3
"""Builds the SQL that switches module-review (Telegram) or module-publish (Instagram) to real mode.

Reads secrets from the environment, prints SQL on stdout (pipe it to psql via stdin, so values never
reach a process list). With --dry-run the secret values are masked and nothing is applied.
Usage: real-mode.py review|publish [--dry-run]
"""
import json
import os
import sys


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def need(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"missing {name}")
    return v


def secret(key: str, value: str, dry: bool) -> str:
    shown = "'***'" if dry else q(value)
    return (f"INSERT INTO module_secrets (key, value) VALUES ({q(key)}, {shown}) "
            f"ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();")


def setting(key: str, value: object) -> str:
    return (f"INSERT INTO module_settings (key, value) VALUES ({q(key)}, {q(json.dumps(value))}::jsonb) "
            f"ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();")


def s3(dry: bool) -> list[str]:
    secure = os.environ.get("S3_PUBLIC_SECURE", "0") in ("1", "true")
    cfg = {"endpoint": "minio:9000", "public_endpoint": os.environ.get("S3_PUBLIC_ENDPOINT", "127.0.0.1:56000"),
           "bucket": os.environ.get("S3_BUCKET", "manufacture"), "secure": False, "public_secure": secure,
           "region": "us-east-1"}
    return [secret("s3.access_key", os.environ.get("MINIO_ROOT_USER", "manufacture"), dry),
            secret("s3.secret_key", os.environ.get("MINIO_ROOT_PASSWORD", ""), dry), setting("s3", cfg)]


def main() -> None:
    kind = sys.argv[1]
    dry = "--dry-run" in sys.argv
    out = ["BEGIN;"]
    if kind == "review":
        out.append(secret("telegram.bot_token", need("TELEGRAM_BOT_TOKEN"), dry))
        ids = lambda n: [int(x) for x in need(n).replace(" ", "").split(",")]  # noqa: E731
        out += [setting("telegram.mode", "real"), setting("telegram.api_base", "https://api.telegram.org"),
                setting("telegram.admin_ids", {"ids": ids("TELEGRAM_ADMIN_IDS")}),
                setting("telegram.chat_ids", {"ids": ids("TELEGRAM_CHAT_IDS")})]
        out += s3(dry)
    elif kind == "publish":
        token, uid = need("INSTAGRAM_ACCESS_TOKEN"), need("INSTAGRAM_USER_ID")
        shown = "'***'" if dry else q(token)
        out.append(f"UPDATE platform_accounts SET external_id = {q(uid)}, access_token = {shown}, "
                   f"updated_at = now() WHERE channel_id = 'itim' AND platform = 'instagram';")
        out += [setting("instagram.mode", "real")] + s3(dry)
    else:
        sys.exit("usage: real-mode.py review|publish [--dry-run]")
    out.append("COMMIT;")
    print("\n".join(out))


main()
