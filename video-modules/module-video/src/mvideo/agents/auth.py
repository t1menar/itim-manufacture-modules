"""Authentication of the agent container: exactly one variable per mode (04 section 10).

Variable names verified against claude-agent-sdk 0.2.179 / Claude Code 2.1.319:
`CLAUDE_CODE_OAUTH_TOKEN` (token from `claude setup-token`, subscription) and `ANTHROPIC_API_KEY`.
The value comes from the core for this job only; it lives in memory, goes to the container
environment, is never written to disk or logs and is scrubbed from transcripts.
"""

from __future__ import annotations

from typing import Literal

from mvideo.core_client import Credential

VAR_BY_MODE: dict[str, str] = {"subscription": "CLAUDE_CODE_OAUTH_TOKEN", "api_key": "ANTHROPIC_API_KEY"}
ALL_AUTH_VARS = frozenset(VAR_BY_MODE.values()) | {"ANTHROPIC_AUTH_TOKEN"}
REDACTED = "[REDACTED]"


def auth_env(mode: Literal["subscription", "api_key"], credential: Credential) -> dict[str, str]:
    """The single auth variable of `mode`; never both."""
    return {VAR_BY_MODE[mode]: credential.value}


def scrub(text: str, secrets: list[str]) -> str:
    """Replace every secret value (and any `sk-ant-...` looking token) in `text`."""
    for s in secrets:
        if s:
            text = text.replace(s, REDACTED)
    return text
