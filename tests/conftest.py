"""
Shared fixtures: live uvicorn servers, started once per session.

The servers listen on consecutive ports from the inclusive range
$WEBSITE_TEST_PORT_MIN..$WEBSITE_TEST_PORT_MAX so the dev server on
$WEBSITE_INTERNAL_PORT can stay up. No httpx / TestClient dependency - API tests
hit the live servers with urllib.
"""

import itertools
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

import pytest

SRC_DIR = Path(__file__).parent.parent / "src"
# The inclusive port range every live server in the suite draws from, one
# consecutive port each (allocated through next_test_port) - the session
# fixtures below plus the servers individual tests start for themselves.
# Factory-only configuration variants need no server - and no port.
PORT_MIN = int(os.environ.get("WEBSITE_TEST_PORT_MIN", "11120"))
PORT_MAX = int(os.environ.get("WEBSITE_TEST_PORT_MAX", "11199"))
if PORT_MIN > PORT_MAX:
    # Caught here rather than in next_test_port, where an inverted range would
    # surface as the "widen the range" error below - misleading advice when
    # the range is not too narrow but backwards.
    raise RuntimeError(
        "WEBSITE_TEST_PORT_MIN..WEBSITE_TEST_PORT_MAX is inverted"
        f" ({PORT_MIN}..{PORT_MAX}) - MIN must not be greater than MAX"
    )

_ports = itertools.count(PORT_MIN)


def next_test_port() -> int:
    """
    Hand out the next unused port of the configured range.

    A counter rather than a per-caller offset: an offset has to be unique
    across every module that starts a server, which nothing checks, and a
    duplicate would surface as the readiness poll timing out - a startup
    error for what is really a bookkeeping mistake. Callers just ask.

    The consequence is that a port belongs to a run, not to a fixture: which
    server lands on which port depends on the order pytest reaches them, so
    read the port off the fixture when debugging rather than assuming one.
    """
    port = next(_ports)
    if port > PORT_MAX:
        raise RuntimeError(
            f"test server port {port} is outside the configured"
            f" WEBSITE_TEST_PORT_MIN..WEBSITE_TEST_PORT_MAX range"
            f" ({PORT_MIN}..{PORT_MAX}) - widen the range to add"
            " another server"
        )
    return port


def _kill_and_reap(proc: subprocess.Popen[bytes]) -> None:
    """SIGKILL `proc` and wait for it, so no zombie outlives the failure."""
    proc.kill()
    # kill() only delivers the signal. Without the wait() the child stays a
    # zombie for the rest of the session, and Popen.__del__ later reports it
    # as "still running" - a ResourceWarning that buries the real error.
    proc.wait()


def start_server(
    port: int,
    env: dict[str, str],
    extra_args: tuple[str, ...] = (),
    *,
    app_target: str = "app.main:app",
    output: IO[bytes] | None = None,
) -> subprocess.Popen[bytes]:
    """
    Start uvicorn on `port` with exactly `env` and return it once healthy.

    `app_target` is the import string uvicorn serves; it defaults to the
    deployed entry point, which is what nearly every test wants. A test that
    needs behavior the real app never exhibits (tests/failing_app.py, which
    raises on purpose) points it at its own module instead - still through
    `app.main`, so what is under test is the real logging setup.

    `output` collects the server's whole log stream (stdout and stderr into
    one file, as a terminal or `docker logs` would show it); the default
    inherits this process's streams, so a failing run's output still reaches
    the pytest report.
    """
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            app_target,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            *extra_args,
        ],
        cwd=SRC_DIR,
        env=env,
        stdout=output,
        stderr=subprocess.STDOUT if output is not None else None,
    )
    health_url = f"http://127.0.0.1:{port}/api/health"
    deadline = time.monotonic() + 15
    while True:
        try:
            with urllib.request.urlopen(health_url, timeout=1):
                return proc
        except urllib.error.HTTPError as err:
            # The server is up but health failed - fail fast with the real
            # status instead of spinning until the deadline. (HTTPError is
            # an OSError subclass, so this except must come first.)
            _kill_and_reap(proc)
            raise RuntimeError(f"/api/health returned HTTP {err.code}") from err
        except OSError as err:
            if proc.poll() is not None:
                # No reap needed: the poll() that detected the exit did it.
                raise RuntimeError("uvicorn exited before becoming ready") from err
            if time.monotonic() > deadline:
                _kill_and_reap(proc)
                raise RuntimeError("uvicorn did not become ready in 15s") from err
            time.sleep(0.2)


@contextmanager
def run_server(
    port: int,
    env: dict[str, str],
    extra_args: tuple[str, ...] = (),
    *,
    app_target: str = "app.main:app",
    output: IO[bytes] | None = None,
) -> Iterator[str]:
    """
    Start uvicorn on `port` with exactly `env`, yield its base URL when healthy.

    The server is stopped and reaped before the block ends, so an `output`
    file is complete and flushed by the time the caller reads it.
    """
    proc = start_server(port, env, extra_args, app_target=app_target, output=output)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        # SIGINT, not terminate(): uvicorn shuts down gracefully on both, but
        # after SIGTERM it re-raises the signal, killing the process without
        # running atexit hooks - and atexit is where coverage saves this
        # subprocess's data (see [tool.coverage.run] in pyproject.toml).
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # uvicorn ignored the signal - don't let teardown hang the suite
            _kill_and_reap(proc)


@pytest.fixture(scope="session")
def server() -> Iterator[str]:
    """Start the server most tests hit, once per session."""
    # Docs on, explicitly: the suite tests the /docs page and its CSP
    # exception, so it must not depend on the shell's environment. And
    # WEBSITE_TRUSTED_HOSTS unset, so the host allowlist under test is the
    # code's default, not whatever the shell carries (the dev container's
    # compose environment sets the variable).
    env = {k: v for k, v in os.environ.items() if k != "WEBSITE_TRUSTED_HOSTS"}
    with run_server(next_test_port(), {**env, "WEBSITE_ENABLE_DOCS": "1"}) as base_url:
        yield base_url


@pytest.fixture(scope="session")
def prefixed_server() -> Iterator[str]:
    """
    Start a server deployed under the URL prefix /prefix.

    --root-path is uvicorn's stand-in for a reverse proxy that mounts the app
    at /prefix and strips the prefix before forwarding: requests arrive at
    unprefixed paths, but every URL the app generates must carry /prefix
    (tests/test_url_prefix.py asserts exactly that).

    Docs on, explicitly, same as `server`: --root-path is also what makes
    uvicorn set scope["path"] to "/prefix" + the request path (see the ASGI
    spec and uvicorn's full_path = root_path + path), so this is the fixture
    that exercises the docs-under-a-prefix CSP check in
    tests/test_url_prefix.py.
    """
    with run_server(
        next_test_port(),
        {**os.environ, "WEBSITE_ENABLE_DOCS": "1"},
        ("--root-path", "/prefix"),
    ) as base_url:
        yield base_url


@pytest.fixture(scope="session")
def trusted_hosts_server() -> Iterator[str]:
    """
    Start a server with an explicit WEBSITE_TRUSTED_HOSTS allowlist.

    site.example stands in for a deployment's public host name (the Host a
    reverse proxy forwards). 127.0.0.1 stays in the list, exactly as the
    variable's documentation demands: the readiness poll in start_server
    probes it, mirroring the distribution image's HEALTHCHECK - dropping it
    would hang this fixture the same way it would mark that container
    unhealthy.
    """
    with run_server(
        next_test_port(),
        {**os.environ, "WEBSITE_TRUSTED_HOSTS": "127.0.0.1,site.example"},
    ) as base_url:
        yield base_url
