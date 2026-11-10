"""Validate POST /v1/jobs bodies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from publish.api.problems import ProblemError
from publish.contract import JobRequest


@dataclass(frozen=True, slots=True)
class ValidJob:
    request: JobRequest
    deadline: datetime


def validate_job(raw: Any) -> ValidJob:
    if not isinstance(raw, dict):
        raise ProblemError(422, "input_invalid", "Request body must be a JSON object")
    try:
        request = JobRequest.model_validate(raw)
    except ValidationError as exc:
        raise ProblemError(422, "input_invalid", "Job request is malformed", errors=exc.errors()) from exc
    if request.stage != "publish":
        raise ProblemError(
            422, "stage_unsupported", f"This module serves stage 'publish', not {request.stage!r}"
        )
    inp = request.input if isinstance(request.input, dict) else {}
    idea_ref = inp.get("idea_ref")
    if not isinstance(idea_ref, dict) or idea_ref.get("id") is None or idea_ref.get("rev") is None:
        raise ProblemError(422, "input_invalid", "Publish jobs need input.idea_ref {id,rev}")
    intents = inp.get("intents")
    if not isinstance(intents, list) or not intents:
        raise ProblemError(422, "input_invalid", "Publish jobs need input.intents")
    try:
        deadline = datetime.fromisoformat(request.deadline.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProblemError(422, "input_invalid", "deadline must be ISO-8601") from exc
    return ValidJob(request=request, deadline=deadline)
