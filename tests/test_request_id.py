"""
Request correlation: the ID on the response, in the log, and gone afterwards.

The point of the ID is to turn "it broke at 14:32" into one grep, so the
guards here follow that chain end to end: every response carries an ID, error
responses produced without an endpoint included; a usable inbound ID is kept
so a trace survives the hop; and the access line uvicorn writes for the
request - the line that says *which* request - carries the same ID.
"""

import asyncio
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.middleware import RequestIDMiddleware
from app.observability import (
    NO_REQUEST_ID,
    REQUEST_ID_HEADER,
    bind_request_id,
    get_request_id,
)

from .conftest import allocate_test_port, run_server

# uuid4().hex, the shape of a minted ID. Asserted rather than "some string":
# it is what distinguishes a minted ID from an echoed one below.
MINTED_ID = re.compile(r"[0-9a-f]{32}")


def _request_id_of(
    url: str, *, sent: str | None = None, host: str | None = None
) -> str:
    """Return the ID the server put on its response to one GET of `url`."""
    headers = {}
    if sent is not None:
        headers[REQUEST_ID_HEADER] = sent
    if host is not None:
        headers["Host"] = host
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return str(response.headers[REQUEST_ID_HEADER])
    except urllib.error.HTTPError as error:
        # An error response is a response: it must carry an ID just the same,
        # and those are the ones anybody actually goes looking for.
        with error:
            return str(error.headers[REQUEST_ID_HEADER])


def test_a_request_without_an_id_is_given_one(server: str) -> None:
    assert MINTED_ID.fullmatch(_request_id_of(f"{server}/api/health"))


def test_each_request_gets_its_own_id(server: str) -> None:
    """Two requests are two traces - an ID nobody can tell apart is no ID."""
    first = _request_id_of(f"{server}/api/health")
    second = _request_id_of(f"{server}/api/health")
    assert first != second


def test_a_usable_inbound_id_is_kept(server: str) -> None:
    """
    A caller's ID is echoed, not replaced.

    That is what makes one ID span a whole call chain: a gateway (or a client
    debugging its own bug report) picks the ID, and this service files its
    logs under the same one instead of starting a second, unlinkable trace.
    """
    assert _request_id_of(f"{server}/api/health", sent="caller-chosen-id") == (
        "caller-chosen-id"
    )


@pytest.mark.parametrize(
    ("unusable", "why"),
    [
        ("", "empty - nothing to correlate on"),
        ("x" * 65, "past the length bound, so a header could bloat every log line"),
        ("has a space", "would split the field for anything that reads log columns"),
        ("id\xe9", "non-ASCII: not encodable as a header value by every hop"),
    ],
)
def test_an_unusable_inbound_id_is_replaced_not_rejected(
    server: str, unusable: str, why: str
) -> None:
    """
    A malformed inbound ID yields a fresh one - and never a failed request.

    Correlation is a diagnostic: refusing the request would turn a cosmetic
    header problem at some upstream into an outage. Echoing it unchecked is
    the other wrong answer, so the assertion pins both halves - the response
    carries a minted ID, and it is not what was sent.
    """
    request_id = _request_id_of(f"{server}/api/health", sent=unusable)
    assert request_id != unusable, why
    assert MINTED_ID.fullmatch(request_id), why


@pytest.mark.parametrize("injected", ["a\r\nb", "a\nb", "a\x00b", "a\x7fb"])
def test_a_control_character_never_reaches_the_header_or_the_log(
    injected: str,
) -> None:
    """
    An ID carrying control characters is replaced, not passed through.

    Not driven over the wire like the cases above, because uvicorn's parser
    already refuses these requests outright - which is exactly why the check
    needs its own test: the app's guard is the backstop for the hops that are
    laxer than uvicorn (a proxy that rewrites headers, a future server, an
    in-process caller). Passing one of these through would let a client split
    the response header it lands in, or forge a whole line in the log.
    """
    with bind_request_id(injected) as request_id:
        assert MINTED_ID.fullmatch(request_id)


@pytest.mark.parametrize(
    ("path", "produced_by"),
    [
        ("/no-such-page", "the branded 404 handler"),
        ("/api/no-such-endpoint", "FastAPI's JSON 404"),
        ("/docs", "a route the docs CSP relaxation applies to"),
    ],
)
def test_responses_that_never_reach_an_endpoint_are_correlated(
    server: str, path: str, produced_by: str
) -> None:
    """Every response carries an ID, whatever produced it."""
    assert MINTED_ID.fullmatch(_request_id_of(f"{server}{path}")), produced_by


def test_a_rejected_host_is_correlated(server: str) -> None:
    """
    TrustedHostMiddleware's 400 carries an ID too.

    It is rejected inside the framework stack, before any route matches, so
    this is what proves the correlation wrapper sits outside all of it: the
    one request an operator most wants to find in the log is the one that was
    turned away.
    """
    assert MINTED_ID.fullmatch(_request_id_of(server, host="attacker.example"))


def test_a_body_cap_413_is_correlated(server: str) -> None:
    """
    The body guard's pre-routing 413 carries an ID.

    That 413 is sent by hand from BodySizeLimitMiddleware before any
    framework code sees the request, which makes it the other wrapper-order
    proof: correlation must sit outside the body guard, or the response
    naming the oversized request would be the one nobody can find.
    """
    request = urllib.request.Request(
        f"{server}/api/shout", data=b"x" * 1_000_001, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=5):
            raise AssertionError("an over-cap body should have been refused")
    except urllib.error.HTTPError as error:
        with error:
            assert error.code == 413
            assert MINTED_ID.fullmatch(str(error.headers[REQUEST_ID_HEADER]))


def test_the_id_does_not_outlive_the_request() -> None:
    """
    The ID is unset again once the response is done cleanly.

    Each ASGI request runs in its own context, so a leak is invisible under a
    real server - until the app is embedded somewhere that reuses a task, and
    a background job starts logging under the last visitor's ID. The clean
    path only: an exception deliberately keeps the binding, and the test
    below pins down why.

    Driven inside one coroutine on purpose: awaiting the middleware directly
    keeps it in this context, where a missing reset would show. Handing it to
    asyncio.run would prove nothing, because a Task gets a copy of the context
    and would discard the leak along with everything else it set.
    """
    seen_inside = ""

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal seen_inside
        seen_inside = get_request_id()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        pass

    scope: Scope = {"type": "http", "method": "GET", "path": "/", "headers": []}

    async def drive() -> str:
        await RequestIDMiddleware(inner)(scope, receive, send)
        return get_request_id()

    after = asyncio.run(drive())
    assert MINTED_ID.fullmatch(seen_inside), "no ID reached the wrapped app"
    assert after == NO_REQUEST_ID


def test_an_unhandled_exception_is_logged_under_the_request_id() -> None:
    """
    The binding survives an exception unwinding through the middleware.

    Uvicorn catches an unhandled exception *above* this middleware and only
    then logs the traceback ("Exception in ASGI application") - the record
    an operator most wants to find by ID. Resetting the ContextVar while the
    exception unwinds would file that traceback under `-`, so the reset is
    the clean path's alone; this asserts the ID is still bound where the
    server's error logger runs, i.e. after the middleware call has raised.
    """

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("kaboom")

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        pass

    scope: Scope = {"type": "http", "method": "GET", "path": "/", "headers": []}

    async def drive() -> str:
        try:
            await RequestIDMiddleware(inner)(scope, receive, send)
        except RuntimeError:
            # Where uvicorn's "Exception in ASGI application" record is made.
            return get_request_id()
        raise AssertionError("the exception should have propagated")

    assert MINTED_ID.fullmatch(asyncio.run(drive()))


def test_the_log_stream_carries_the_id_of_the_request_it_describes(
    tmp_path: Path,
) -> None:
    """
    Uvicorn's access line and the app's own lines share one ID and one stream.

    The whole feature is worth nothing if the line naming the request that
    failed is the one line without an ID, and uvicorn writes that line through
    loggers of its own - which is why app.observability adopts them (see
    "Request correlation" in docs/ARCHITECTURE.md) rather than only
    configuring the root logger. Driven through a real server because that
    adoption is a claim about uvicorn's logging setup, not about ours.

    Startup lines are checked in the same pass: they have no request, so they
    must say so rather than borrow an ID or crash the formatter.
    """
    log_path = tmp_path / "server.log"
    with (
        log_path.open("wb") as sink,
        run_server(allocate_test_port(4), dict(os.environ), output=sink) as base,
    ):
        urllib.request.urlopen(
            urllib.request.Request(
                f"{base}/api/health", headers={REQUEST_ID_HEADER: "traced-id"}
            ),
            timeout=5,
        ).close()
    log = log_path.read_text()

    assert re.search(
        r'INFO uvicorn\.access \[traced-id\] .* "GET /api/health HTTP/1\.1" 200', log
    ), f"no access line correlated to the request that produced it:\n{log}"
    assert re.search(
        rf"INFO app\.lifecycle \[{NO_REQUEST_ID}\] Serving static files", log
    ), f"the startup line is not marked as belonging to no request:\n{log}"
