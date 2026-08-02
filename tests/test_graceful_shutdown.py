"""
Guards for the distribution image's bounded graceful shutdown.

Uvicorn's own graceful-shutdown default is *no* limit: after
SIGTERM it waits for every in-flight request, however long that takes. Under
an orchestrator that turns a rolling deploy into a stall - the replica hangs
until the termination grace period expires and SIGKILL cuts the connections
mid-response, which is the opposite of draining them. The distribution image
therefore configures an explicit timeout (see "Bounded graceful shutdown" in
docs/ARCHITECTURE.md).

Two halves, because neither proves the behavior alone: that the image's
environment still carries a finite timeout, and that a finite timeout really
does end a shutdown a stuck request would otherwise hold open. The behavioral
half uses a short timeout of its own - the mechanism is what is testable in
seconds, not the image's 20.
"""

import os
import signal
import socket
import subprocess
import time
from pathlib import Path

import pytest

from .conftest import SRC_DIR, next_test_port, start_server_command
from .helpers import distribution_entrypoint, distribution_environment

# Short enough to keep the suite quick, long enough that the exit is
# unambiguously the timeout expiring rather than a race with startup.
TIMEOUT_SECONDS = 2
REPO_ROOT = Path(__file__).parent.parent


def test_distribution_command_bounds_graceful_shutdown() -> None:
    """The image configures Uvicorn with a finite, positive shutdown timeout."""
    default = distribution_environment().get("UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN", "")
    assert default.isdigit(), (
        "the distribution stage declares no shutdown timeout default"
    )
    assert int(default) > 0, (
        "a zero timeout would abandon in-flight requests instead of draining them"
    )

    assert distribution_entrypoint() == ["uvicorn", "app.main:app"]


def test_shutdown_ends_even_with_a_request_in_flight() -> None:
    """A request that never completes cannot outlast the configured timeout."""
    port = next_test_port()
    environment = {
        **distribution_environment(),
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(SRC_DIR),
        "UVICORN_HOST": "127.0.0.1",
        "UVICORN_PORT": str(port),
        "UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN": str(TIMEOUT_SECONDS),
    }
    proc = start_server_command(
        distribution_entrypoint(),
        port,
        environment,
        cwd=REPO_ROOT,
    )
    stuck = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        # A request the server can never finish: the declared body never
        # arrives, so the endpoint stays awaiting it. Unbounded, this alone
        # keeps uvicorn alive until something kills it.
        stuck.sendall(
            b"POST /api/shout HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 50\r\n"
            b"\r\n"
            b'{"message":'
        )
        time.sleep(0.5)  # let the server pick the request up before signalling

        started = time.monotonic()
        # SIGTERM, the signal an orchestrator sends (docker stop, a pod
        # deletion) - not the SIGINT the fixtures use for coverage's sake.
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=TIMEOUT_SECONDS + 15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("uvicorn never exited: the shutdown timeout did not apply")
        assert time.monotonic() - started >= TIMEOUT_SECONDS, (
            "shutdown finished before the timeout, so the request was never"
            " actually in flight and this test proves nothing"
        )
    finally:
        stuck.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
