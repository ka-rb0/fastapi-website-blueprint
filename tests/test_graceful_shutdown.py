"""
Guards for the distribution image's bounded graceful shutdown.

Uvicorn's own `--timeout-graceful-shutdown` default is *no* limit: after
SIGTERM it waits for every in-flight request, however long that takes. Under
an orchestrator that turns a rolling deploy into a stall - the replica hangs
until the termination grace period expires and SIGKILL cuts the connections
mid-response, which is the opposite of draining them. The distribution image
therefore passes an explicit timeout (see "Bounded graceful shutdown" in
docs/ARCHITECTURE.md).

Two halves, because neither proves the behavior alone: that the image's
command still carries a finite timeout, and that a finite timeout really does
end a shutdown a stuck request would otherwise hold open. The behavioral half
uses a short timeout of its own - the mechanism is what is testable in
seconds, not the image's 20.
"""

import json
import os
import re
import signal
import socket
import subprocess
import time
from pathlib import Path

import pytest

from .conftest import next_test_port, start_server

REPO_ROOT = Path(__file__).parent.parent
DOCKERFILE = REPO_ROOT / ".devcontainer" / "Dockerfile"

# Short enough to keep the suite quick, long enough that the exit is
# unambiguously the timeout expiring rather than a race with startup.
TIMEOUT_SECONDS = 2


def test_distribution_command_bounds_graceful_shutdown() -> None:
    """The image's CMD passes uvicorn a finite, positive shutdown timeout."""
    dockerfile = DOCKERFILE.read_text()

    default = re.search(
        r"^ENV WEBSITE_GRACEFUL_SHUTDOWN_SECONDS=(\d+)$", dockerfile, re.MULTILINE
    )
    assert default, "the distribution stage declares no shutdown timeout default"
    assert int(default.group(1)) > 0, (
        "a zero timeout would abandon in-flight requests instead of draining them"
    )

    cmd = next(
        (line for line in dockerfile.splitlines() if line.startswith("CMD ")), ""
    )
    assert cmd, "the distribution stage has no CMD"
    # Exec-form CMD is a JSON array; parsing it yields the shell command with
    # the backslash-escaped quotes resolved, so the assertions below read the
    # arguments uvicorn actually receives.
    command = " ".join(json.loads(cmd.removeprefix("CMD ")))
    assert "uvicorn app.main:app" in command, "the CMD under test moved"
    assert (
        '--timeout-graceful-shutdown "${WEBSITE_GRACEFUL_SHUTDOWN_SECONDS}"' in command
    ), "without this flag uvicorn waits forever for in-flight requests"


def test_shutdown_ends_even_with_a_request_in_flight() -> None:
    """A request that never completes cannot outlast the configured timeout."""
    port = next_test_port()
    proc = start_server(
        port,
        dict(os.environ),
        ("--timeout-graceful-shutdown", str(TIMEOUT_SECONDS)),
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
