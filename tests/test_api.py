"""API tests against the live uvicorn server (see conftest.py)."""

import json
import urllib.error
import urllib.request

import pytest

from app.main import DOCS_CSP, MAX_SHOUT_LENGTH, SECURITY_HEADERS


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


def test_unknown_path_serves_404_page(server: str) -> None:
    """Unknown non-API paths get the branded 404 page - with a real 404 status."""
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(f"{server}/no-such-page", timeout=5)
    assert excinfo.value.code == 404
    assert excinfo.value.headers["Content-Type"].startswith("text/html")
    assert "<h1>Page not found</h1>" in excinfo.value.read().decode()


@pytest.mark.parametrize("path", ["/api", "/api/", "/api/no-such-endpoint"])
def test_unknown_api_path_stays_json(server: str, path: str) -> None:
    """API clients keep getting JSON 404s, not the HTML page - bare /api included."""
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(f"{server}{path}", timeout=5)
    assert excinfo.value.code == 404
    assert excinfo.value.headers["Content-Type"] == "application/json"


@pytest.mark.parametrize("path", ["/", "/api/health"])
def test_security_headers(server: str, path: str) -> None:
    """
    The ASGI wrapper puts the headers on every response - static and API alike.

    Error responses are covered in test_security_headers.py.
    """
    with urllib.request.urlopen(f"{server}{path}", timeout=5) as resp:
        for name, value in SECURITY_HEADERS.items():
            assert resp.headers[name] == value


def test_index_served(server: str) -> None:
    with urllib.request.urlopen(server, timeout=5) as resp:
        assert resp.status == 200
        assert "<title>FastAPI Website Blueprint</title>" in resp.read().decode()


def test_docs_page_served(server: str) -> None:
    """/docs serves FastAPI's Swagger UI page (conftest enables the docs)."""
    with urllib.request.urlopen(f"{server}/docs", timeout=5) as resp:
        assert resp.status == 200
        assert '<div id="swagger-ui">' in resp.read().decode()


def test_docs_gets_relaxed_csp(server: str) -> None:
    """
    /docs responses carry DOCS_CSP; every other security header is unchanged.

    That the relaxation stays off all other paths is covered by
    test_security_headers above, which asserts the strict CSP exactly.
    """
    with urllib.request.urlopen(f"{server}/docs", timeout=5) as resp:
        assert resp.headers["Content-Security-Policy"] == DOCS_CSP
        for name, value in SECURITY_HEADERS.items():
            if name != "Content-Security-Policy":
                assert resp.headers[name] == value


def test_openapi_schema_served(server: str) -> None:
    """The schema the docs page reads stays at the FastAPI default URL."""
    with urllib.request.urlopen(f"{server}/openapi.json", timeout=5) as resp:
        assert resp.status == 200
        schema = json.load(resp)
    assert "/api/shout" in schema["paths"]
