from __future__ import annotations

import time

from mvideo.ids import uuid7


def test_uuid7_version_and_variant() -> None:
    u = uuid7()
    assert u.version == 7
    assert u.variant == "specified in RFC 4122"


def test_uuid7_is_ordered_by_time() -> None:
    first = uuid7()
    time.sleep(0.003)
    second = uuid7()
    assert first < second


def test_uuid7_unique() -> None:
    assert len({uuid7() for _ in range(5000)}) == 5000
