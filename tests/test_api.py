"""API tests against the live uvicorn server (see conftest.py)."""

import json
import urllib.error
import urllib.request

import pytest


def _post_json(url: str, body: bytes) -> urllib.request.Request:
    return urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )


def test_health(server: str) -> None:
    with urllib.request.urlopen(f"{server}/api/health", timeout=5) as resp:
        assert resp.status == 200
        assert json.load(resp) == {"status": "ok"}


def test_shout_uppercases(server: str) -> None:
    req = _post_json(f"{server}/api/shout", b'{"text": "hello, World"}')
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        assert json.load(resp) == {"text": "HELLO, WORLD"}


def test_shout_rejects_bodies_without_text(server: str) -> None:
    """Pydantic validates the body - a missing `text` field is a 422, not a 500."""
    req = _post_json(f"{server}/api/shout", b"{}")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req, timeout=5)
    assert excinfo.value.code == 422


def test_index_served(server: str) -> None:
    with urllib.request.urlopen(server, timeout=5) as resp:
        assert resp.status == 200
        assert "<title>FastAPI Website Blueprint</title>" in resp.read().decode()
