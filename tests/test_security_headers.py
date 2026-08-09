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

from app.config import Settings
from app.factory import create_app
from app.middleware import (
    DOCS_COOP,
    DOCS_CSP,
    SECURITY_HEADERS,
    SecurityHeadersMiddleware,
)
from tests.helpers import framework_app


def test_app_is_wrapped_outside_the_framework() -> None:
    """
    Factory-built apps are the wrappers, header stamp outermost.

    That ordering is what guarantees headers on ServerErrorMiddleware's 500s
    - and on any response sent while the body-size guard is in the stack.
    Via create_app, not `from app.main import app`: importing app.main
    constructs an env-configured app, so a stray shell variable would kill
    collection of this whole module (docs/ARCHITECTURE.md bans the import
    for exactly that reason). The entry point itself is exercised by the
    live-server fixtures, which run `uvicorn app.main:app` in subprocesses.
    """
    framework_app(create_app(Settings()))


def _directives(csp: str) -> dict[str, str]:
    return dict(directive.split(" ", 1) for directive in csp.split("; "))


def test_docs_csp_relaxes_exactly_scripts_styles_connects_and_images() -> None:
    """
    DOCS_CSP is the strict CSP with exactly four directives loosened.

    Guards the derivation in app.middleware: if the strict policy were
    reworded, a silently no-op replace would ship the strict CSP to /docs
    (blank page) - and nothing else may ever diverge between the two.
    """
    base = _directives(SECURITY_HEADERS["Content-Security-Policy"])
    docs = _directives(DOCS_CSP)
    cdn = "'self' 'unsafe-inline' https://cdn.jsdelivr.net"
    assert docs.pop("script-src") == cdn
    assert docs.pop("style-src") == cdn
    assert docs.pop("connect-src") == "'self' https://cdn.jsdelivr.net"
    assert docs.pop("img-src") == "'self' data: https://fastapi.tiangolo.com"
    del base["script-src"], base["style-src"], base["connect-src"], base["img-src"]
    assert docs == base


def test_docs_opener_policy_supports_oauth_popups() -> None:
    """Swagger's cross-origin OAuth popup must retain window.opener."""
    assert SECURITY_HEADERS["Cross-Origin-Opener-Policy"] == "same-origin"
    assert DOCS_COOP == "same-origin-allow-popups"


async def _crashing_app(scope: Scope, receive: Receive, send: Send) -> None:
    raise RuntimeError("boom")


def test_headers_on_unhandled_exception_500() -> None:
    """A 500 produced by ServerErrorMiddleware still carries every header."""
    wrapped = SecurityHeadersMiddleware(
        ServerErrorMiddleware(_crashing_app), docs_enabled=False
    )
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
