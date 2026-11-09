"""Parse and validate Manufacture artifact refs (`s3://bucket/key`)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ObjectRef:
    bucket: str
    key: str

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"


def parse_s3_ref(ref: str, *, require_bucket: str | None = "manufacture") -> ObjectRef:
    """Parse `s3://bucket/key…`. Reject empty keys and unexpected buckets when required."""
    raw = (ref or "").strip()
    if not raw.startswith("s3://"):
        raise ValueError(f"not an s3:// ref: {ref!r}")
    rest = raw[len("s3://") :]
    bucket, sep, key = rest.partition("/")
    if not sep or not bucket or not key or key.startswith("/"):
        raise ValueError(f"malformed s3:// ref: {ref!r}")
    if "//" in key or key.endswith("/"):
        raise ValueError(f"malformed s3 object key: {ref!r}")
    if require_bucket is not None and bucket != require_bucket:
        raise ValueError(f"unexpected bucket {bucket!r}, want {require_bucket!r}")
    return ObjectRef(bucket=bucket, key=key)
