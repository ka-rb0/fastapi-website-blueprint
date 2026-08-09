"""
RateLimitMiddleware, driven as plain ASGI plus one live server.

The unit tests below own the limiter's numbers, because a rate is a claim
about time and a test that waits for real seconds to pass is a test that
fails on a loaded CI runner. The clock is replaced instead, so refilling is
asserted exactly rather than approximately. The live server at the end is
there for the parts no in-process call can prove: that a 429 leaves the real
stack carrying what every other response carries, and that a limited server
still answers the probes an orchestrator restarts it for failing.

Every shared fixture in conftest.py runs with the limiter off (see UNLIMITED
there), so this file is the only place its numbers are exercised.
"""

import asyncio
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from typing import NamedTuple

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from starlette.types import Message, Receive, Scope, Send

from app import middleware as middleware_module
from app.middleware import (
    RATE_LIMIT_WINDOW_SECONDS,
    SECURITY_HEADERS,
    RateLimitMiddleware,
)
from app.observability import REQUEST_ID_HEADER
from app.routers.probes import LIVENESS_PATH, PROBE_PATHS, READINESS_PATH

from .conftest import next_test_port, run_server

CLIENT = ("203.0.113.5", 54321)
OTHER_CLIENT = ("198.51.100.9", 41234)

# Small enough that a test can exhaust it in a readable loop, and a rate whose
# refill interval (six seconds per token) is a round number to assert against.
LIMIT = 10
SECONDS_PER_TOKEN = RATE_LIMIT_WINDOW_SECONDS / LIMIT

# What the eviction tests below shrink the client table to. The production cap
# is sized for a busy replica; driving thousands of addresses through the
# limiter would assert the same behavior far more slowly.
TRACKED_CLIENTS = 4

Advance = Callable[[float], None]


class Sent(NamedTuple):
    """What the limiter sent, or (None, {}) when the request reached the app."""

    status: int | None
    headers: dict[str, str]


async def _reached_app(scope: Scope, receive: Receive, send: Send) -> None:
    """Stand in for the wrapped stack, answering nothing."""


async def _receive() -> Message:
    """Deliver one empty body - the limiter decides before anything reads it."""
    return {"type": "http.request", "body": b"", "more_body": False}


def _call(
    limiter: RateLimitMiddleware,
    *,
    path: str = "/",
    root_path: str = "",
    client: tuple[str, int] | None = CLIENT,
    scope_type: str = "http",
) -> Sent:
    """Drive one request through `limiter` and return what it answered, if anything."""
    captured: list[Message] = []

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            captured.append(message)

    scope: Scope = {
        "type": scope_type,
        "method": "GET",
        "path": path,
        "root_path": root_path,
        "headers": [],
        "client": client,
    }
    asyncio.run(limiter(scope, _receive, send))
    if not captured:
        return Sent(None, {})
    start = captured[0]
    return Sent(
        start["status"],
        {name.decode().lower(): value.decode() for name, value in start["headers"]},
    )


def _limiter(requests_per_minute: int = LIMIT) -> RateLimitMiddleware:
    """Build a limiter over the do-nothing app, exempting the probe paths."""
    return RateLimitMiddleware(
        _reached_app,
        requests_per_minute=requests_per_minute,
        exempt_paths=PROBE_PATHS,
    )


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Advance:
    """
    Freeze the limiter's clock and return a function that advances it.

    Patched on the module rather than injected through the constructor: the
    seam exists for this file only, and a production parameter that nothing
    in production passes is API surface bought for a test.
    """
    now = 0.0

    def advance(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr(middleware_module, "monotonic", lambda: now)
    return advance


@pytest.fixture
def small_table(monkeypatch: pytest.MonkeyPatch) -> int:
    """Shrink the tracked-client cap so eviction is reachable in a few calls."""
    monkeypatch.setattr(middleware_module, "RATE_LIMIT_MAX_CLIENTS", TRACKED_CLIENTS)
    return TRACKED_CLIENTS


@pytest.mark.usefixtures("clock")
def test_a_burst_up_to_the_limit_is_allowed() -> None:
    """The whole minute's allowance is spendable at once, with time stopped."""
    limiter = _limiter()
    assert [_call(limiter).status for _ in range(LIMIT)] == [None] * LIMIT


@pytest.mark.usefixtures("clock")
def test_the_request_past_the_limit_is_refused() -> None:
    """The first request with no token left gets a 429, not a slow 200."""
    limiter = _limiter()
    for _ in range(LIMIT):
        _call(limiter)

    refused = _call(limiter)
    assert refused.status == 429
    assert refused.headers["content-type"] == "application/json"


def test_the_refusal_advertises_when_to_retry(clock: Advance) -> None:
    """
    Retry-After names a moment a retry actually succeeds at.

    Rounded up rather than down (see _consume): the second the token is
    *nearly* there is a second the retry is refused again, which teaches a
    well-behaved client that honoring the header does not work.
    """
    limiter = _limiter()
    for _ in range(LIMIT):
        _call(limiter)

    assert _call(limiter).headers["retry-after"] == str(int(SECONDS_PER_TOKEN))

    clock(SECONDS_PER_TOKEN)
    assert _call(limiter).status is None


def test_tokens_refill_continuously(clock: Advance) -> None:
    """
    Waiting buys back exactly the elapsed fraction, not a whole window.

    The distinction is what a fixed window gets wrong: there, a client that
    spends its allowance late in one window and early in the next issues
    twice the limit across the boundary.
    """
    limiter = _limiter()
    for _ in range(LIMIT):
        _call(limiter)

    clock(SECONDS_PER_TOKEN * 3)
    assert [_call(limiter).status for _ in range(3)] == [None] * 3
    assert _call(limiter).status == 429


def test_refilling_never_exceeds_the_burst(clock: Advance) -> None:
    """An idle client comes back with a full bucket, never a bigger one."""
    limiter = _limiter()
    _call(limiter)

    clock(RATE_LIMIT_WINDOW_SECONDS * 100)
    assert [_call(limiter).status for _ in range(LIMIT + 1)] == [None] * LIMIT + [429]


@pytest.mark.usefixtures("clock")
def test_clients_are_limited_separately() -> None:
    """One address exhausting its bucket leaves every other address untouched."""
    limiter = _limiter()
    for _ in range(LIMIT + 1):
        _call(limiter)

    assert _call(limiter, client=OTHER_CLIENT).status is None


@pytest.mark.usefixtures("clock")
@pytest.mark.parametrize("path", PROBE_PATHS)
def test_probe_paths_are_never_limited(path: str) -> None:
    """
    An orchestrator's polling neither spends the allowance nor is refused by it.

    A limited probe is the worst failure this middleware could produce: the
    orchestrator reads a 429 as unhealthy and restarts a replica that was
    serving fine, on a schedule, forever.
    """
    limiter = _limiter()
    polls = LIMIT * 5
    assert [_call(limiter, path=path).status for _ in range(polls)] == [None] * polls
    assert [_call(limiter).status for _ in range(LIMIT)] == [None] * LIMIT


@pytest.mark.usefixtures("clock")
def test_probe_paths_are_exempt_behind_a_url_prefix() -> None:
    """
    The exemption follows root_path, because the comparison strips it first.

    Comparing the raw path would limit the probes of every prefixed
    deployment - the failure mode this project has already hit twice
    elsewhere (see the root_path note in AGENTS.md).
    """
    limiter = _limiter()
    statuses = [
        _call(limiter, path=f"/prefix{LIVENESS_PATH}", root_path="/prefix").status
        for _ in range(LIMIT + 1)
    ]
    assert statuses == [None] * (LIMIT + 1)


@pytest.mark.usefixtures("clock")
def test_a_path_normalizing_onto_a_probe_is_still_limited() -> None:
    """
    Exemption is exact, so dot segments cannot borrow one they resolve onto.

    Normalizing here would *widen* the exemption rather than narrow a
    relaxation - the same reasoning that keeps the Host allowlist's exemption
    exact, and the opposite of the CSP check's.
    """
    limiter = _limiter()
    dotted = f"{LIVENESS_PATH}/../shout"
    statuses = [_call(limiter, path=dotted).status for _ in range(LIMIT + 1)]
    assert statuses[-1] == 429


@pytest.mark.usefixtures("clock")
def test_requests_without_a_client_address_pass_through() -> None:
    """
    No address means no identity to limit, so the request is served.

    ASGI marks scope["client"] optional and embedding transports leave it
    unset. Refusing those would apply a limit on nobody to everybody.
    """
    limiter = _limiter()
    calls = LIMIT * 3
    assert [_call(limiter, client=None).status for _ in range(calls)] == [None] * calls


@pytest.mark.usefixtures("clock")
def test_a_zero_limit_disables_the_middleware() -> None:
    """0 is the documented off switch for a deployment whose ingress limits."""
    limiter = _limiter(requests_per_minute=0)
    calls = LIMIT * 10
    assert [_call(limiter).status for _ in range(calls)] == [None] * calls


@pytest.mark.usefixtures("clock")
def test_non_http_scopes_pass_through() -> None:
    """A lifespan (or websocket) scope carries no request to charge to anyone."""
    limiter = _limiter()
    assert _call(limiter, scope_type="lifespan").status is None


@pytest.mark.usefixtures("clock")
def test_the_client_table_stays_bounded(small_table: int) -> None:
    """
    Tracking never grows past the cap, however many addresses are seen.

    The table is keyed on the source address, so an unbounded one would let a
    spray from a large address pool exhaust the memory of the very replica
    this middleware exists to protect.
    """
    limiter = _limiter()
    for index in range(small_table * 5):
        _call(limiter, client=(f"192.0.2.{index}", 1234))

    assert len(limiter._buckets) == small_table


@pytest.mark.usefixtures("clock")
def test_eviction_drops_the_least_recently_seen_client(small_table: int) -> None:
    """
    A client mid-limit survives the eviction a spray of new addresses triggers.

    This is what makes the bound safe rather than a bypass: the entry that
    leaves is the idlest one, whose bucket had refilled to what a first-time
    client is handed anyway, while the address actually being limited stays
    tracked because it keeps being seen.
    """
    limiter = _limiter()
    for _ in range(LIMIT + 1):
        _call(limiter)

    for index in range(small_table * 5):
        _call(limiter, client=(f"192.0.2.{index}", 1234))
        # Keep the exhausted client the most recently seen one, exactly as a
        # client that is still hammering the site would be.
        assert _call(limiter).status == 429


@settings(max_examples=50, deadline=None)
@given(
    waits=st.lists(st.floats(min_value=0, max_value=30), max_size=40),
    limit=st.integers(min_value=1, max_value=120),
)
def test_allowances_never_exceed_the_rate_over_any_run(
    waits: list[float], limit: int
) -> None:
    """
    Whatever the arrival pattern, allowed <= burst + rate * elapsed.

    The token bucket's defining guarantee, stated against the clock rather
    than against the implementation: no interleaving of waits and requests
    can buy more than the configured rate plus the one burst the bucket
    starts full with. Bursts, long idles and zero-length gaps are all covered
    by the one property, which is what the cases above cannot enumerate.
    """
    now = 0.0
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(middleware_module, "monotonic", lambda: now)
        limiter = _limiter(requests_per_minute=limit)
        allowed = 0
        for wait in waits:
            now += wait
            if _call(limiter).status is None:
                allowed += 1

    assert allowed <= limit + limit * (now / RATE_LIMIT_WINDOW_SECONDS)


@pytest.fixture(scope="module")
def limited_server() -> Iterator[str]:
    """
    Start a server whose limiter is on, at a rate one test can exhaust.

    Module-scoped and deliberately shared: the second test below wants a
    server whose allowance the first one has already spent, which is the
    state a replica gets killed in if the probe exemption is wrong.
    """
    with run_server(
        next_test_port(),
        {**os.environ, "WEBSITE_RATE_LIMIT_PER_MINUTE": str(LIMIT)},
    ) as base_url:
        yield base_url


def test_a_live_429_carries_what_every_response_carries(limited_server: str) -> None:
    """
    The refusal is stamped and correlated like any other response.

    This is what the wrapper order buys (see "Composition root" in
    docs/ARCHITECTURE.md): the limiter sits *inside* the correlation and
    header wrappers, so a refused request is still findable in the log by the
    ID the client was handed, and still cannot be framed or sniffed. A
    limiter registered with add_middleware, or wrapped around the outside,
    would answer without either.
    """
    refused = None
    for _ in range(LIMIT + 1):
        try:
            urllib.request.urlopen(f"{limited_server}/", timeout=5).close()
        except urllib.error.HTTPError as error:
            refused = error
            break

    assert refused is not None, f"{LIMIT + 1} requests did not exhaust {LIMIT}/min"
    assert refused.code == 429
    assert refused.headers[REQUEST_ID_HEADER]
    assert int(refused.headers["Retry-After"]) > 0
    assert (
        refused.headers["Content-Security-Policy"]
        == SECURITY_HEADERS["Content-Security-Policy"]
    )
    assert json.load(refused) == {"detail": "Rate limit exceeded"}


def test_a_limited_server_still_answers_its_probes(limited_server: str) -> None:
    """
    The probes keep answering after the allowance is spent, over a real server.

    The test above already exhausted this server's bucket for the loopback,
    so the probes here are asked from the same address as the flood - which
    is exactly how an orchestrator asks, and why the exemption exists.
    """
    for path in (LIVENESS_PATH, READINESS_PATH):
        with urllib.request.urlopen(f"{limited_server}{path}", timeout=5) as response:
            assert response.status == 200
