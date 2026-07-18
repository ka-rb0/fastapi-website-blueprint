"""
Shared fixtures: one uvicorn server for the whole test run.

The server listens on $WEBSITE_TEST_PORT (falling back to 20177, e.g. in CI)
so the dev server on $WEBSITE_INTERNAL_PORT can stay up. No httpx /
TestClient dependency - API tests hit the live server with urllib.
"""

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).parent.parent / "src"
PORT = int(os.environ.get("WEBSITE_TEST_PORT", "20177"))
BASE_URL = f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="session")
def server() -> Iterator[str]:
    """Start uvicorn once per session and yield its base URL."""
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
        ],
        cwd=SRC_DIR,
        # Docs on, explicitly: the suite tests the /docs page and its CSP
        # exception, so it must not depend on the shell's environment.
        env={**os.environ, "WEBSITE_ENABLE_DOCS": "1"},
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                with urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=1):
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
        yield BASE_URL
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
