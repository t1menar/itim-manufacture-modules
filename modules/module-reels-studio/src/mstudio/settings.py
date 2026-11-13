"""Settings from the environment (`MSTUDIO_*`). Secrets are read here and never passed to Claude Code."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    reels_dir: Path = field(default_factory=lambda: Path(_env("MSTUDIO_REELS_DIR", str(Path.home() / "itim/Reels"))))
    state_dir: Path = field(
        default_factory=lambda: Path(_env("MSTUDIO_STATE_DIR", str(Path.home() / ".local/state/reels-studio")))
    )
    claude_bin: str = field(default_factory=lambda: _env("MSTUDIO_CLAUDE_BIN", str(Path.home() / ".local/bin/claude")))
    model: str = field(default_factory=lambda: _env("MSTUDIO_MODEL", "claude-opus-5-5"))
    effort: str = field(default_factory=lambda: _env("MSTUDIO_EFFORT", "high"))
    probe_model: str = field(default_factory=lambda: _env("MSTUDIO_PROBE_MODEL", "haiku"))
    permission_mode: str = field(default_factory=lambda: _env("MSTUDIO_PERMISSION_MODE", "auto"))
    # wait for the reset when less than this share of a usage window is left (0.30 = 30%)
    min_left: float = field(default_factory=lambda: float(_env("MSTUDIO_MIN_LEFT", "0.30")))
    max_attempts: int = field(default_factory=lambda: int(_env("MSTUDIO_MAX_ATTEMPTS", "3")))
    max_rounds: int = field(default_factory=lambda: int(_env("MSTUDIO_ERROR_ROUNDS", "2")))
    # "off" disables the notices (tests); default: the review bot's token and owners
    tg_token: str = field(
        default_factory=lambda: (
            "" if _env("MSTUDIO_TG_TOKEN") == "off" else _env("MSTUDIO_TG_TOKEN") or _env("MTGR_BOT_TOKEN")
        )
    )
    tg_chats: tuple[int, ...] = field(
        default_factory=lambda: tuple(
            int(x) for x in (_env("MSTUDIO_TG_CHATS") or _env("MTGR_OWNERS")).split(",") if x.strip()
        )
    )
    blob_prefix: str = field(default_factory=lambda: _env("MSTUDIO_BLOB_PREFIX", ""))
    feed: bool = field(default_factory=lambda: _env("MSTUDIO_FEED", "on") != "off")  # ideas file + source trigger

    @property
    def db_path(self) -> Path:
        return self.state_dir / "studio.db"

    @property
    def log_dir(self) -> Path:
        return self.state_dir / "logs"


# Environment variables never handed to Claude Code (it runs with the user's own Claude login).
SECRET_PREFIXES = ("MF_", "S3_", "MSTUDIO_TG", "MTGR_", "MIPUB_", "MIDEA_", "RABBITMQ_", "POSTGRES_")
SECRET_NAMES = {"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}


def child_env() -> dict[str, str]:
    """The environment for Claude Code: everything except the secrets of the stack."""
    return {
        k: v
        for k, v in os.environ.items()
        if k not in SECRET_NAMES and not any(k.startswith(p) for p in SECRET_PREFIXES)
    }
