"""
BodySizeLimitMiddleware branches the live-server tests can't reach.

The 413 paths (oversized Content-Length, oversized chunked stream) run
against real servers in test_api.py; this file drives the middleware as
plain ASGI for the message flow a well-behaved HTTP client never produces.
"""

import asyncio
from collections.abc import Iterator

from starlette.types import Message, Receive, Scope, Send

from app.main import BodySizeLimitMiddleware


def test_non_body_messages_pass_through_uncounted() -> None:
    """
    http.disconnect flows through the guard to the app, unchanged.

    A client that vanishes mid-request makes the server deliver
    http.disconnect instead of another body chunk - the guard must hand
    such messages through without counting them against the cap, so the
    app can run its own disconnect handling.
    """
    seen: list[Message] = []

    async def inner_app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(await receive())
        seen.append(await receive())

    messages: Iterator[Message] = iter(
        [
            {"type": "http.request", "body": b"x", "more_body": True},
            {"type": "http.disconnect"},
        ]
    )

    async def receive() -> Message:
        return next(messages)

    async def send(message: Message) -> None:
        raise AssertionError("no response expected from the inner app")

    scope: Scope = {"type": "http", "method": "POST", "path": "/", "headers": []}
    guarded = BodySizeLimitMiddleware(inner_app, max_body_bytes=10)
    asyncio.run(guarded(scope, receive, send))
    assert [message["type"] for message in seen] == ["http.request", "http.disconnect"]
