"""
Shared fixtures: live uvicorn servers, started once per session.

The servers listen on consecutive ports from the inclusive range
$WEBSITE_TEST_PORT_MIN..$WEBSITE_TEST_PORT_MAX (falling back to 20177..20179,
e.g. in CI) so the dev server on $WEBSITE_INTERNAL_PORT can stay up. No
httpx / TestClient dependency - API tests hit the live servers with urllib.
"""

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

import pytest

SRC_DIR = Path(__file__).parent.parent / "src"
# The inclusive port range the server fixtures below draw from, one
# consecutive port per fixture (allocated through _test_port). Factory-only
# configuration variants need no server - and no port.
PORT_MIN = int(os.environ.get("WEBSITE_TEST_PORT_MIN", "20177"))
PORT_MAX = int(os.environ.get("WEBSITE_TEST_PORT_MAX", "20179"))
if PORT_MIN > PORT_MAX:
    # Caught here rather than in _test_port, where an inverted range would
    # surface as the "widen the range" error below - misleading advice when
    # the range is not too narrow but backwards.
    raise RuntimeError(
        "WEBSITE_TEST_PORT_MIN..WEBSITE_TEST_PORT_MAX is inverted"
        f" ({PORT_MIN}..{PORT_MAX}) - MIN must not be greater than MAX"
    )


def _test_port(offset: int) -> int:
    """Return the offset-th port of the configured range, refusing to leave it."""
    port = PORT_MIN + offset
    if not PORT_MIN <= port <= PORT_MAX:
        raise RuntimeError(
            f"test server port {port} is outside the configured"
            f" WEBSITE_TEST_PORT_MIN..WEBSITE_TEST_PORT_MAX range"
            f" ({PORT_MIN}..{PORT_MAX}) - widen the range to add"
            " another server fixture"
        )
    return port


@contextmanager
def _run_server(
    port: int, env: dict[str, str], extra_args: tuple[str, ...] = ()
) -> Iterator[str]:
    """Start uvicorn on `port` with exactly `env`, yield its base URL when healthy."""
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            *extra_args,
        ],
        cwd=SRC_DIR,
        env=env,
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                with urllib.request.urlopen(f"{base_url}/api/health", timeout=1):
                    break
            except urllib.error.HTTPError as err:
                # The server is up but health failed - fail fast with the real
                # status instead of spinning until the deadline. (HTTPError is
                # an OSError subclass, so this except must come first.)
                raise RuntimeError(f"/api/health returned HTTP {err.code}") from err
            except OSError as err:
                if proc.poll() is not None:
                    raise RuntimeError("uvicorn exited before becoming ready") from err
                if time.monotonic() > deadline:
                    raise RuntimeError("uvicorn did not become ready in 15s") from err
                time.sleep(0.2)
        yield base_url
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
            proc.kill()
            proc.wait()


@pytest.fixture(scope="session")
def server() -> Iterator[str]:
    """Start the server most tests hit, once per session."""
    # Docs on, explicitly: the suite tests the /docs page and its CSP
    # exception, so it must not depend on the shell's environment. And
    # WEBSITE_TRUSTED_HOSTS unset, so the host allowlist under test is the
    # code's default, not whatever the shell carries (the dev container's
    # compose environment sets the variable).
    env = {k: v for k, v in os.environ.items() if k != "WEBSITE_TRUSTED_HOSTS"}
    with _run_server(_test_port(0), {**env, "WEBSITE_ENABLE_DOCS": "1"}) as base_url:
        yield base_url


@pytest.fixture(scope="session")
def prefixed_server() -> Iterator[str]:
    """
    Start a server deployed under the URL prefix /prefix, one port up.

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
    with _run_server(
        _test_port(1),
        {**os.environ, "WEBSITE_ENABLE_DOCS": "1"},
        ("--root-path", "/prefix"),
    ) as base_url:
        yield base_url


@pytest.fixture(scope="session")
def trusted_hosts_server() -> Iterator[str]:
    """
    Start a server with an explicit WEBSITE_TRUSTED_HOSTS allowlist, two ports up.

    site.example stands in for a deployment's public host name (the Host a
    reverse proxy forwards). 127.0.0.1 stays in the list, exactly as the
    variable's documentation demands: the readiness poll in _run_server
    probes it, mirroring the distribution image's HEALTHCHECK - dropping it
    would hang this fixture the same way it would mark that container
    unhealthy.
    """
    with _run_server(
        _test_port(2),
        {**os.environ, "WEBSITE_TRUSTED_HOSTS": "127.0.0.1,site.example"},
    ) as base_url:
        yield base_url
