"""
Security headers on framework-generated error responses.

The live-server tests in test_api.py cover successful responses, but the app
has no route that crashes, so the unhandled-exception path is driven here as
plain ASGI: same middleware ordering as production (SecurityHeadersMiddleware
outside ServerErrorMiddleware), no extra HTTP client dependency.
"""

import asyncio
from typing import Any

import pytest
from starlette.middleware.errors import ServerErrorMiddleware
from starlette.types import Message, Receive, Scope, Send

from app.main import SECURITY_HEADERS, SecurityHeadersMiddleware, app, fastapi_app


def test_app_is_wrapped_outside_the_framework() -> None:
    """
    The served `app` must be the wrapper, outermost.

    That ordering is what guarantees headers on ServerErrorMiddleware's 500s.
    """
    assert isinstance(app, SecurityHeadersMiddleware)
    assert app.app is fastapi_app


async def _crashing_app(scope: Scope, receive: Receive, send: Send) -> None:
    raise RuntimeError("boom")


def test_headers_on_unhandled_exception_500() -> None:
    """A 500 produced by ServerErrorMiddleware still carries every header."""
    wrapped = SecurityHeadersMiddleware(ServerErrorMiddleware(_crashing_app))
    messages: list[Message] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request"}

    async def send(message: Message) -> None:
        messages.append(message)

    scope: Scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    # ServerErrorMiddleware re-raises after sending its 500, so the server can
    # log the exception - the response has been sent by then.
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(wrapped(scope, receive, send))

    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 500
    headers = {
        name.decode().lower(): value.decode() for name, value in start["headers"]
    }
    for name, value in SECURITY_HEADERS.items():
        assert headers[name.lower()] == value
