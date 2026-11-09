from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from review.api.problems import ProblemError


@dataclass(frozen=True, slots=True)
class ValidJob:
    job_id: UUID
    attempt: int
    fence: int
    production_id: UUID
    mode: str
    round: int
    variant_id: UUID | None
    input: dict[str, Any]
    settings: dict[str, Any]
    callback_base_url: str
    deadline: datetime
    raw: dict[str, Any]


def validate_job(raw: Any) -> ValidJob:
    if not isinstance(raw, dict):
        raise ProblemError(422, "input_invalid", "Request body must be a JSON object")
    try:
        job_id = UUID(str(raw["job_id"]))
        production_id = UUID(str(raw["production_id"]))
        stage = str(raw.get("stage") or "")
        if stage != "review":
            raise ProblemError(422, "stage_unsupported", f"expected review, got {stage!r}")
        mode = str(raw.get("mode") or "create")
        fence = int(raw.get("fence") or 1)
        attempt = int(raw.get("attempt") or 1)
        round_n = int(raw.get("round") or 1)
        variant = raw.get("variant")
        variant_id = UUID(str(variant["id"])) if isinstance(variant, dict) and variant.get("id") else None
        callback = raw.get("callback") or {}
        base = str(callback.get("base_url") or "")
        if not base:
            raise ProblemError(422, "input_invalid", "callback.base_url required")
        deadline = datetime.fromisoformat(str(raw["deadline"]).replace("Z", "+00:00"))
        settings = raw.get("settings") or {}
        values = settings.get("values") if isinstance(settings, dict) else {}
        job_input = dict(raw.get("input") or {})
        if "idea" in job_input:
            raise ProblemError(422, "input_invalid", "input.idea removed (D21); use input.idea_ref {id,rev}")
        ref = job_input.get("idea_ref")
        if not isinstance(ref, dict) or ref.get("id") is None or ref.get("rev") is None:
            raise ProblemError(422, "input_invalid", "input.idea_ref {id,rev} required")
        return ValidJob(
            job_id=job_id,
            attempt=attempt,
            fence=fence,
            production_id=production_id,
            mode=mode,
            round=round_n,
            variant_id=variant_id,
            input=job_input,
            settings=dict(values or {}),
            callback_base_url=base,
            deadline=deadline,
            raw=raw,
        )
    except ProblemError:
        raise
    except Exception as exc:
        raise ProblemError(422, "input_invalid", f"malformed job: {exc}") from exc
