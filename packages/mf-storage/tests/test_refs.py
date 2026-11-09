from __future__ import annotations

import pytest

from mf_storage.refs import parse_s3_ref


def test_parse_ok() -> None:
    ref = parse_s3_ref("s3://manufacture/pid/video/1/final.mp4")
    assert ref.bucket == "manufacture"
    assert ref.key == "pid/video/1/final.mp4"
    assert ref.uri.startswith("s3://manufacture/")


def test_reject_bad() -> None:
    with pytest.raises(ValueError):
        parse_s3_ref("https://x")
    with pytest.raises(ValueError):
        parse_s3_ref("s3://other/x")
    with pytest.raises(ValueError):
        parse_s3_ref("s3://manufacture/")
