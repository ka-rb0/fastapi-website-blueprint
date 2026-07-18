"""API tests against the live uvicorn server (see conftest.py)."""

import json
import urllib.error
import urllib.request

import pytest

from app.main import MAX_SHOUT_LENGTH, SECURITY_HEADERS


def _post_json_request(url: str, body: bytes) -> urllib.request.Request:
    """Build (not send) a POST request; method explicit rather than implied by data=."""
    return urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )


def test_health(server: str) -> None:
    with urllib.request.urlopen(f"{server}/api/health", timeout=5) as resp:
        assert resp.status == 200
        assert json.load(resp) == {"status": "ok"}


def test_shout_uppercases(server: str) -> None:
    req = _post_json_request(f"{server}/api/shout", b'{"text": "hello, World"}')
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        assert json.load(resp) == {"text": "HELLO, WORLD"}


def test_shout_rejects_bodies_without_text(server: str) -> None:
    """Pydantic validates the body - a missing `text` field is a 422, not a 500."""
    req = _post_json_request(f"{server}/api/shout", b"{}")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req, timeout=5)
    assert excinfo.value.code == 422


def test_shout_rejects_oversized_text(server: str) -> None:
    """`text` carries an explicit max_length - oversized input is a 422, not a 500."""
    body = json.dumps({"text": "x" * (MAX_SHOUT_LENGTH + 1)}).encode()
    req = _post_json_request(f"{server}/api/shout", body)
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req, timeout=5)
    assert excinfo.value.code == 422


@pytest.mark.parametrize("path", ["/", "/api/health"])
def test_security_headers(server: str, path: str) -> None:
    """The middleware puts the headers on every response - static and API alike."""
    with urllib.request.urlopen(f"{server}{path}", timeout=5) as resp:
        for name, value in SECURITY_HEADERS.items():
            assert resp.headers[name] == value


def test_index_served(server: str) -> None:
    with urllib.request.urlopen(server, timeout=5) as resp:
        assert resp.status == 200
        assert "<title>FastAPI Website Blueprint</title>" in resp.read().decode()
