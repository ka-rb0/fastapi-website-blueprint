"""
BodySizeLimitMiddleware branches the live-server tests can't reach.

The 413 paths (oversized Content-Length, oversized chunked stream) run
against real servers in test_api.py; this file drives the middleware as
plain ASGI for the message flow a well-behaved HTTP client never produces.
"""

import asyncio
import re
from collections.abc import Iterator

import pytest
from hypothesis import given
from hypothesis import strategies as st
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Message, Receive, Scope, Send

from app.middleware import BodySizeLimitMiddleware, _declared_body_length

# RFC 9110's Content-Length is `1*DIGIT`. Spelled out here from the spec
# rather than imported from the parser, so the property below compares the
# implementation against the grammar instead of against itself.
RFC_9110_CONTENT_LENGTH = re.compile(rb"[0-9]+")


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


@pytest.mark.parametrize("declared", [b"not-a-number", b"1_000", b"\xc2\xb2"])
def test_an_unparseable_content_length_still_gets_the_streaming_cap(
    declared: bytes,
) -> None:
    """
    A malformed Content-Length caps the stream instead of crashing the stack.

    Uvicorn's parser answers these with a 400 before the app is called, so
    over the wire this is unreachable - but the wrapper is public API an
    embedding host may drive directly (as this file does), and a ValueError
    escaping here would escape *outside* ServerErrorMiddleware, leaving the
    client with no response at all. The cap must still hold, which is what
    the 413 below asserts: the declaration is ignored, the bytes are not.

    Each value is one way int() is laxer than RFC 9110's `1*DIGIT`: garbage
    it refuses outright, an underscore separator it silently reads as 1000,
    and a superscript two that str.isdigit() alone would accept and int()
    would then refuse - which is why the check is `isascii() and isdigit()`.
    """
    statuses: list[int] = []

    async def inner_app(scope: Scope, receive: Receive, send: Send) -> None:
        while (await receive()).get("more_body"):
            pass

    async def receive() -> Message:
        return {"type": "http.request", "body": b"x" * 20, "more_body": True}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"content-length", declared)],
    }
    guarded = BodySizeLimitMiddleware(inner_app, max_body_bytes=10)
    # The framework the wrapper normally sits outside of is what turns this
    # into a response; driven bare, the HTTPException is the observable result.
    with pytest.raises(StarletteHTTPException) as raised:
        asyncio.run(guarded(scope, receive, send))
    assert raised.value.status_code == 413
    assert statuses == [], "the request was rejected up front, not as it streamed"


@given(
    st.one_of(
        st.binary(max_size=16),
        # Latin-1 because that is how Headers decodes a raw value, so this is
        # the strategy that can produce the str forms int() and str.isdigit()
        # disagree about ("²", "1_000") rather than their UTF-8 encodings.
        st.text(alphabet="0123456789+-_ ²³\t", max_size=16).map(
            lambda value: value.encode("latin-1")
        ),
    )
)
def test_a_length_is_read_from_exactly_the_values_rfc_9110_allows(
    declared: bytes,
) -> None:
    """
    Any Content-Length yields the declared size, or nothing - never an exception.

    The parametrized cases above name three ways int() is laxer than the
    grammar; this is the same claim without a list of guesses behind it, and
    it is the property that actually matters: this function runs before
    anything has framed the request, outside ServerErrorMiddleware, so a
    ValueError escaping it leaves the client with no response at all. That
    the call returns rather than raises is asserted by reaching the next
    line - what the assertions add is that the *accepted* values are exactly
    the grammar's, so a future edit cannot widen it back to int()'s.
    """
    length = _declared_body_length(Headers(raw=[(b"content-length", declared)]))
    if RFC_9110_CONTENT_LENGTH.fullmatch(declared):
        assert length == int(declared)
    else:
        assert length is None
