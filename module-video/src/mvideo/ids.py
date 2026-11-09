"""UUID v7 (time-ordered) identifiers, the system convention for ids (AUTHORING section 4)."""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """48-bit millisecond timestamp, version 7, 74 random bits (RFC 9562 section 5.7)."""
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= (rand >> 68) << 64  # rand_a: top 12 of the 80 random bits
    value |= 0b10 << 62
    value |= rand & ((1 << 62) - 1)  # rand_b: low 62 bits
    return uuid.UUID(int=value)
