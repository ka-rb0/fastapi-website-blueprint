"""
Shared fixtures: live uvicorn servers, started once per session.

The servers listen on $WEBSITE_TEST_PORT and the next port up (falling back
to 20177, e.g. in CI) so the dev server on $WEBSITE_INTERNAL_PORT can stay
up. No httpx / TestClient dependency - API tests hit the live servers with
urllib.
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
# The first port of the range the fixtures below use ($WEBSITE_TEST_PORT
# itself for `server`, +1 for `docs_disabled_server`).
BASE_PORT = int(os.environ.get("WEBSITE_TEST_PORT", "20177"))


@contextmanager
def _run_server(port: int, env: dict[str, str]) -> Iterator[str]:
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
    # exception, so it must not depend on the shell's environment.
    with _run_server(BASE_PORT, {**os.environ, "WEBSITE_ENABLE_DOCS": "1"}) as base_url:
        yield base_url


@pytest.fixture(scope="session")
def docs_disabled_server() -> Iterator[str]:
    """
    Start a second server with WEBSITE_ENABLE_DOCS unset, for testing the gating.

    The flag is read at app import, so covering both sides takes two server
    processes. One port up from `server` - the two run concurrently.
    """
    env = {k: v for k, v in os.environ.items() if k != "WEBSITE_ENABLE_DOCS"}
    with _run_server(BASE_PORT + 1, env) as base_url:
        yield base_url
