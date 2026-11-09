"""Validation of POST /v1/jobs with the rejection codes of 04 section 9 (HTTP 422).

Order: envelope, stage, language, settings, input, credential reference, revise requirements.
Nothing is stored for a rejected request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from mvideo.api.problems import ProblemError
from mvideo.contract import JobInput, JobRequest
from mvideo.settings_model import VideoSettings


@dataclass(frozen=True, slots=True)
class ValidJob:
    request: JobRequest
    settings: VideoSettings
    input: JobInput


def _errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()]


def validate_job(raw: Any) -> ValidJob:
    if not isinstance(raw, dict):
        raise ProblemError(422, "input_invalid", "Request body must be a JSON object")
    try:
        request = JobRequest.model_validate(raw)
    except ValidationError as exc:
        raise ProblemError(422, "input_invalid", "Job request is malformed", errors=_errors(exc)) from exc

    if request.stage != "video":
        raise ProblemError(
            422, "stage_unsupported", f"This module serves stage 'video', not {request.stage!r}"
        )

    idea = request.input.get("idea")
    language = idea.get("language") if isinstance(idea, dict) else None
    if language != "en":
        raise ProblemError(
            422, "language_unsupported", f"Stage 1 is English only; idea.language is {language!r}"
        )

    try:
        settings = VideoSettings.model_validate(request.settings.values)
    except ValidationError as exc:
        raise ProblemError(
            422, "settings_invalid", "Settings snapshot is invalid", errors=_errors(exc)
        ) from exc

    try:
        job_input = JobInput.model_validate(request.input)
    except ValidationError as exc:
        raise ProblemError(422, "input_invalid", "Job input is invalid", errors=_errors(exc)) from exc

    ref = settings.agent.auth.credential_ref
    if ref not in request.credentials:
        raise ProblemError(
            422,
            "settings_invalid",
            f"Credential {ref!r} (agent.auth.credential_ref) is not among the job's credentials",
        )

    if request.mode == "revise":
        if not request.variant or "id" not in request.variant:
            raise ProblemError(422, "input_invalid", "Revise jobs need a variant with an id")
        if job_input.previous is None:
            raise ProblemError(422, "input_invalid", "Revise jobs need input.previous")

    return ValidJob(request=request, settings=settings, input=job_input)
