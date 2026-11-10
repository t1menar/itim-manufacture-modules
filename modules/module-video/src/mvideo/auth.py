"""Bearer authentication of the core (04 section 2): one per-module token, constant-time compare."""

from __future__ import annotations

import hmac

from fastapi import Request

from mvideo.api.problems import ProblemError


def require_bearer(request: Request) -> None:
    expected: str = request.app.state.config.core_token
    header = request.headers.get("authorization", "")
    scheme, _, supplied = header.partition(" ")
    ok = scheme.lower() == "bearer" and hmac.compare_digest(supplied.strip().encode(), expected.encode())
    if not ok:
        raise ProblemError(
            401, "unauthorized", "Missing or wrong bearer token", headers={"WWW-Authenticate": "Bearer"}
        )
