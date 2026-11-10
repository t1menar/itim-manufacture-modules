#!/usr/bin/env python3
"""Register modules in core (idempotent). Runs on the compose network.

Env: CORE_URL, CORE_ADMIN_TOKEN, TOKENS_FILE (optional), X_ADMIN_ACTOR.
Fetches each module /info as manifest, POSTs /internal/v1/modules, writes new mft_ tokens.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

CORE_URL = os.environ["CORE_URL"].rstrip("/")
ADMIN = os.environ["CORE_ADMIN_TOKEN"]
TOKENS_FILE = os.environ.get("TOKENS_FILE") or ""
ACTOR = os.environ.get("X_ADMIN_ACTOR", "deploy:local")


def http(method: str, url: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict | str]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Admin-Actor"] = ACTOR
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        code = e.code
    try:
        parsed: dict | str = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = raw
    return code, parsed


def write_token(var: str, token: str) -> None:
    if not TOKENS_FILE:
        return
    path = Path(TOKENS_FILE)
    lines = path.read_text().splitlines() if path.exists() else []
    out, found = [], False
    for line in lines:
        if line.startswith(var + "="):
            out.append(f"{var}={token}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{var}={token}")
    path.write_text("\n".join(out) + "\n")
    Path(f"/tmp/mf_new_{var}").write_text(token + "\n")


def register_one(module_id: str, name: str, stage: str, endpoint: str, info_url: str, token_var: str) -> None:
    code, info = http("GET", info_url)
    if code != 200 or not isinstance(info, dict):
        raise SystemExit(f"failed to fetch {info_url}: HTTP {code} {info!r}")
    # core modules.Info + DisallowUnknownFields — drop input_schema/output_schema etc.
    allowed = ("name", "version", "contract", "stages", "settings_schema", "admin_endpoints")
    manifest = {k: info[k] for k in allowed if k in info}
    body = {
        "id": module_id,
        "name": name,
        "stage": stage,
        "endpoint": endpoint,
        "enabled": True,
        "manifest": manifest,
    }
    code, resp = http("POST", f"{CORE_URL}/internal/v1/modules", body=body, token=ADMIN)
    if code not in (200, 201):
        raise SystemExit(f"register {module_id} failed HTTP {code}: {resp}")
    token = ""
    if isinstance(resp, dict):
        token = resp.get("token") or ""
    if not token:
        # Idempotent replay: rotate if .env still has a pending placeholder.
        current = ""
        if TOKENS_FILE:
            for line in Path(TOKENS_FILE).read_text().splitlines():
                if line.startswith(token_var + "="):
                    current = line.split("=", 1)[1]
                    break
        if current.startswith("mft_pending") or not current:
            rcode, rresp = http(
                "POST",
                f"{CORE_URL}/internal/v1/modules/{module_id}/token",
                body={},
                token=ADMIN,
            )
            if rcode == 200 and isinstance(rresp, dict):
                token = rresp.get("token") or ""
    if token:
        write_token(token_var, token)
        print(f"registered {module_id} (new token issued)")
    else:
        print(f"registered {module_id} (idempotent, token unchanged)")


def main() -> None:
    register_one(
        "video-claude",
        "Video (Claude Code + renderer)",
        "video",
        "http://module-video:8080",
        "http://module-video:8080/info",
        "MODULE_TOKEN_VIDEO",
    )
    register_one(
        "review-telegram",
        "Review (Telegram bot)",
        "review",
        "http://module-review:8080",
        "http://module-review:8080/info",
        "MODULE_TOKEN_REVIEW",
    )
    register_one(
        "publish-instagram",
        "Publish (Instagram Graph API / fake)",
        "publish",
        "http://module-publish:8080",
        "http://module-publish:8080/info",
        "MODULE_TOKEN_PUBLISH",
    )


if __name__ == "__main__":
    main()
