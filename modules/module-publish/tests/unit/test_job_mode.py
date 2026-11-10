from publish.contract import JobRequest


def test_job_request_accepts_the_republish_mode_core_sends() -> None:
    req = JobRequest.model_validate(
        {
            "job_id": "01a1c660-8ace-76bb-bea3-caeb91ae2c6d",
            "attempt": 4,
            "production_id": "01a1c551-bd56-7f0c-beac-ee6d23858a3f",
            "stage": "publish",
            "mode": "republish",
            "input": {},
            "callback": {"base_url": "http://core:8080/internal/v1/jobs/x"},
            "deadline": "2026-11-10T17:22:58Z",
        }
    )
    assert req.mode == "republish"
