"""Maps the facts the runner reports (`_result.json`) and the files of `/out` to an outcome (05 section 4)."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from mvideo.pipeline.errors import StepError

Kind = Literal[
    "outputs",
    "blocked",
    "turns_exceeded",
    "budget_exceeded",
    "rate_limited",
    "auth_failed",
    "failed",
    "unavailable",
]

AUTH_RE = re.compile(
    r"invalid (x-api-key|api key|bearer|token)|authentication[_ ]error"
    r"|oauth token (has )?(expired|revoked|invalid)"
    r"|token.*(expired|revoked)|please run .?/login|failed to authenticate|unauthorized",
    re.I,
)
RATE_RE = re.compile(r"usage limit|rate[_ ]limit|limit reached|too many requests|quota", re.I)


@dataclass(frozen=True, slots=True)
class Outcome:
    kind: Kind
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _text(result: dict[str, Any]) -> str:
    return " ".join([str(result.get("result_text") or ""), *map(str, result.get("errors") or [])])


def classify(
    result: dict[str, Any],
    files: set[str],
    *,
    cost_mode: str = "usd",
    backoff_s: int = 900,
    now: dt.datetime | None = None,
) -> Outcome:
    """Order: blocked.json, outputs, auth, rate limit, turns, budget, other failures."""
    now = now or dt.datetime.now(dt.UTC)
    visible = {f for f in files if not f.startswith("_")}
    if "blocked.json" in visible:
        return Outcome("blocked", "the agent wrote blocked.json")
    if visible:
        return Outcome("outputs")
    status = result.get("api_error_status")
    text = _text(result)
    if status in (401, 403) or (result.get("is_error") and AUTH_RE.search(text)):
        return Outcome("auth_failed", text[:300])
    limit = result.get("rate_limit") or {}
    if (
        status == 429
        or limit.get("status") == "rejected"
        or (result.get("is_error") and RATE_RE.search(text))
    ):
        resets = limit.get("resets_at")
        wait = max(60, int(resets - now.timestamp())) if resets else backoff_s
        return Outcome("rate_limited", text[:300], {"retry_after": wait, "reported": resets is not None})
    sub, why = (
        str(result.get("subtype") or ""),
        str(result.get("terminal_reason") or result.get("stop_reason") or ""),
    )
    if sub == "error_max_turns" or why == "max_turns":
        return Outcome("turns_exceeded", f"max turns reached after {result.get('num_turns')} turns")
    if sub == "error_max_budget_usd" and cost_mode == "usd":
        return Outcome("budget_exceeded", "the step budget was used up without outputs")
    if isinstance(status, int) and status >= 500:
        return Outcome("unavailable", f"Anthropic API error {status}")
    return Outcome("failed", text[:300] or "the agent produced no outputs")


def to_error(outcome: Outcome, step: str) -> StepError | None:
    """The StepError for a failing outcome; None when the step has outputs to validate."""
    k = outcome.kind
    if k == "outputs":
        return None
    table: dict[str, tuple[str, str]] = {
        "rate_limited": ("transient", "agent_rate_limited"),
        "auth_failed": ("blocked", "agent_auth_failed"),
        "turns_exceeded": ("fatal", "turns_exceeded"),
        "budget_exceeded": ("fatal", "budget_exceeded"),
        "unavailable": ("transient", "anthropic_unavailable"),
        "failed": ("fatal", "agent_failed"),
        "blocked": ("blocked", "blocked"),
    }
    cls, code = table[k]
    msg = outcome.message
    if k == "auth_failed":
        msg = "The Claude token is invalid, expired or revoked. An admin must renew it (claude setup-token)."
    return StepError(cls, code, msg or code, step=step, details=dict(outcome.details))  # type: ignore[arg-type]
