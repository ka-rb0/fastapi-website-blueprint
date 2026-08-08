"""
Guards for the distribution image's runtime hardening defaults.

Two settings that only exist in the image's environment, so nothing in
`create_app` can express or enforce them:

- `UVICORN_LIMIT_CONCURRENCY` - the ceiling past which uvicorn sheds load with
  a 503 instead of accepting until the kernel OOM-kills the container.
- `UVICORN_SERVER_HEADER` - off, so responses don't name the stack.

Each is covered the same way as the bounded shutdown in
`tests/test_graceful_shutdown.py`, and for the same reason: that the image
still *declares* the default, and that the mechanism behind it really behaves
as claimed. Neither half proves it alone - a declared variable uvicorn stopped
honoring would pass the first, and a behavior proven with a hand-written
environment says nothing about what the image ships. See "Backpressure" and
"No `Server` header" in docs/ARCHITECTURE.md.
"""

import os
import socket
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.routers.probes import LIVENESS_PATH

from .conftest import SRC_DIR, next_test_port, run_server_command
from .helpers import distribution_entrypoint, distribution_environment

REPO_ROOT = Path(__file__).parent.parent

# Small enough to reach by hand, large enough to leave room for the readiness
# poll's own (already closed) connection - the mechanism is what is testable in
# a unit test, not the image's 512.
TEST_LIMIT = 4


@contextmanager
def _running_image(**overrides: str) -> Iterator[str]:
    """
    Run the image's entrypoint locally with its own ENV defaults, plus overrides.

    The environment is the image's, deliberately not this process's: what the
    image ships is the point, and the dev container's ambient UVICORN_*
    variables would otherwise decide the outcome. PATH and PYTHONPATH stand in
    for the image's layout, as in tests/test_reverse_proxy_config.py.
    """
    port = next_test_port()
    environment = {
        **distribution_environment(),
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(SRC_DIR),
        "UVICORN_PORT": str(port),
        **overrides,
    }
    with run_server_command(
        # --host, because the image binds 0.0.0.0 and a test server has no
        # business on this machine's other interfaces.
        [*distribution_entrypoint(), "--host", "127.0.0.1"],
        port,
        environment,
        cwd=REPO_ROOT,
    ) as base_url:
        yield base_url


def _liveness_status(sock: socket.socket) -> int:
    """Return the status of one GET /livez sent over an open socket."""
    sock.sendall(b"GET /livez HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
    status_line = sock.recv(64).split(b"\r\n", 1)[0]
    return int(status_line.split(b" ")[1])


def test_distribution_declares_a_concurrency_limit() -> None:
    """The image ships a finite, positive ceiling on accepted connections."""
    default = distribution_environment().get("UVICORN_LIMIT_CONCURRENCY", "")
    assert default.isdigit(), (
        "the distribution stage declares no concurrency limit, so a burst is"
        " accepted until the container is OOM-killed"
    )
    assert int(default) > 0, "a zero limit would refuse every request"


def test_excess_connections_are_shed_with_503() -> None:
    """
    Past the limit uvicorn answers 503 rather than accepting without bound.

    Held open *idle*, because that is the half of this setting most easily
    got wrong when tuning it: uvicorn weighs the limit against the
    open-connection count as well as the task count, so a keep-alive
    connection occupies a slot with no request in flight at all.

    Asserted as a range rather than an exact index: a connection the readiness
    poll has already closed can still be counted for a moment, which shifts
    *which* connection is the first to be refused without changing the
    behavior under test.
    """
    with _running_image(UVICORN_LIMIT_CONCURRENCY=str(TEST_LIMIT)) as base_url:
        port = int(base_url.rsplit(":", 1)[1])
        held: list[socket.socket] = []
        statuses: list[int] = []
        try:
            # One more attempt than the limit allows, so the last one is over
            # it however the earlier slots were accounted for.
            for _ in range(TEST_LIMIT + 1):
                sock = socket.create_connection(("127.0.0.1", port), timeout=5)
                held.append(sock)
                statuses.append(_liveness_status(sock))
        finally:
            for sock in held:
                sock.close()

    # Both directions, from one sequence: connections below the limit are
    # served (so this cannot pass against a server that 503s unconditionally),
    # and the excess is refused (so it cannot pass against no limit at all).
    assert statuses[0] == 200, f"the first connection was refused: {statuses}"
    assert 503 in statuses, f"no connection was ever shed: {statuses}"
    served = statuses.index(503)
    assert served <= TEST_LIMIT, f"more than the limit was served: {statuses}"


def test_image_does_not_name_the_server_software() -> None:
    """Responses carry no Server header, while Date - which caches need - stays."""
    with (
        _running_image() as base_url,
        urllib.request.urlopen(f"{base_url}{LIVENESS_PATH}", timeout=5) as response,
    ):
        headers = response.headers
    assert headers.get("Server") is None, (
        "the image advertises its server software, so UVICORN_SERVER_HEADER"
        " is no longer taking effect"
    )
    assert headers.get("Date") is not None
