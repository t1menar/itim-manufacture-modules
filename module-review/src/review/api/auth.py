"""Bearer auth against MODULE_CORE_TOKEN (constant-time)."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, Request

from review.api.problems import problem
from review.bootstrap import BootstrapConfig


class Unauthorized(Exception):
    pass


async def require_core_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    config: BootstrapConfig = request.app.state.config
    if not authorization or not authorization.startswith("Bearer "):
        raise Unauthorized()
    token = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, config.core_token):
        raise Unauthorized()


CoreAuth = Annotated[None, Depends(require_core_token)]


def unauthorized_response() -> object:
    return problem(401, "unauthorized", "Missing or invalid bearer token")
