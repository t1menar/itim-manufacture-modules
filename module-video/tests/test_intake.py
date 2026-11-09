from __future__ import annotations

import copy
from typing import Any

import pytest

from mvideo.api.problems import ProblemError
from mvideo.intake import validate_job
from tests.helpers import job_request, settings_values


def code_of(raw: Any) -> tuple[int, str]:
    with pytest.raises(ProblemError) as err:
        validate_job(raw)
    return err.value.status, err.value.code


def test_valid_create_job() -> None:
    job = validate_job(job_request())
    assert job.request.stage == "video"
    assert job.settings.agent.auth.mode == "subscription"
    assert (job.input.idea_ref.id, job.input.idea_ref.rev) == (42, 1)


def test_not_an_object() -> None:
    assert code_of([]) == (422, "input_invalid")


def test_malformed_envelope() -> None:
    raw = job_request()
    del raw["callback"]
    assert code_of(raw) == (422, "input_invalid")
    assert code_of({**job_request(), "attempt": 0}) == (422, "input_invalid")
    assert code_of({**job_request(), "mode": "rewrite"}) == (422, "input_invalid")
    assert code_of({**job_request(), "deadline": "2026-11-09T12:00:00"}) == (
        422,
        "input_invalid",
    )  # naive time


def test_wrong_stage() -> None:
    assert code_of(job_request(stage="review")) == (422, "stage_unsupported")


def test_settings_are_validated_against_the_schema() -> None:
    assert code_of(job_request(settings={"agent": {"image": "nodigest"}})) == (422, "settings_invalid")
    assert code_of(job_request(settings=settings_values(unknown=1))) == (422, "settings_invalid")


def test_settings_errors_are_listed() -> None:
    with pytest.raises(ProblemError) as err:
        validate_job(job_request(settings={"agent": {"image": "nodigest"}}))
    assert any("agent" in e["loc"] for e in err.value.extra["errors"])


def test_input_is_validated() -> None:
    raw = job_request()
    raw["input"]["idea_ref"]["rev"] = 0
    assert code_of(raw) == (422, "input_invalid")


def test_credential_reference_must_be_listed() -> None:
    assert code_of(job_request(credentials=[])) == (422, "settings_invalid")
    values = settings_values(
        agent={"image": settings_values()["agent"]["image"], "auth": {"credential_ref": "cred:mine"}}
    )
    assert code_of(job_request(settings=values)) == (422, "settings_invalid")
    assert validate_job(job_request(settings=values, credentials=["cred:mine"]))


def test_revise_needs_variant_and_previous() -> None:
    assert code_of(job_request(mode="revise")) == (422, "input_invalid")
    raw = job_request(mode="revise", variant={"id": "0194f3a0-0000-7000-8000-000000000001", "language": "en"})
    assert code_of(raw) == (422, "input_invalid")
    raw2 = copy.deepcopy(raw)
    raw2["input"]["previous"] = {
        "script_ref": "s3://manufacture/p/video/1/script/script.en.json",
        "review_reason": "too fast",
        "round": 1,
    }
    assert validate_job(raw2).request.mode == "revise"
