"""
Guards for deployment under a URL prefix.

Against `prefixed_server` (uvicorn --root-path /prefix, see conftest.py):
the browser resolves a page's links against the site's *public* URL, so a
root-hardcoded /css/theme.css would escape the prefix and miss the app
entirely. The templates generate every URL with url_for (which carries
root_path) and js/shout.js reads the API endpoint from the form's rendered
action attribute - these tests fetch the live pages and assert the prefix
landed everywhere a URL is emitted.
"""

import re
import urllib.error
import urllib.request

import pytest

from app.middleware import DOCS_CSP

# Every static asset the pages reference, by prefix-relative path.
ASSETS = (
    "favicon.svg",
    "css/theme.css",
    "css/style.css",
    "js/theme-init.js",
    "js/theme-switch.js",
    "js/shout.js",
)


def _get_html(url: str, expected_status: int = 200) -> str:
    """GET `url` and return the body, asserting the status on the way."""
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            assert resp.status == expected_status
            body: bytes = resp.read()
            return body.decode()
    except urllib.error.HTTPError as err:
        with err:
            assert err.code == expected_status
            return err.read().decode()


def test_index_asset_urls_carry_prefix(prefixed_server: str) -> None:
    """Every asset URL on the homepage points inside the prefix."""
    html = _get_html(f"{prefixed_server}/")
    for asset in ASSETS:
        assert f"{prefixed_server}/prefix/{asset}" in html, (
            f"{asset} is not referenced under the /prefix root path"
        )


def test_shout_form_action_carries_prefix(prefixed_server: str) -> None:
    """The form metadata js/shout.js submits through points inside the prefix."""
    html = _get_html(f"{prefixed_server}/")
    match = re.search(r'<form\b[^>]*\bid="shout-form"[^>]*>', html, re.DOTALL)
    assert match, '<form id="shout-form" ...> not found in the rendered homepage'
    action = re.search(r'\baction="([^"]*)"', match.group(0))
    assert action, "the shout form carries no action attribute"
    assert action.group(1) == f"{prefixed_server}/prefix/api/shout"


def test_not_found_home_link_carries_prefix(prefixed_server: str) -> None:
    """The 404 page's way home leads to the prefixed site root."""
    html = _get_html(f"{prefixed_server}/no/such/page", expected_status=404)
    assert f'href="{prefixed_server}/prefix/"' in html


def test_unknown_api_path_stays_json_under_a_prefix(prefixed_server: str) -> None:
    """
    /api/... 404s stay JSON when the app runs under --root-path.

    Regression test: branded_404 used to gate on request.url.path, which -
    like scope["path"] - carries the root_path prefix (URL is built straight
    from scope["path"], see starlette.datastructures.URL.__init__). Under a
    reverse proxy, path.startswith("/api/") then silently failed and API
    clients got the branded HTML 404 page instead of a JSON body.
    """
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(f"{prefixed_server}/api/no-such-endpoint", timeout=5)
    assert excinfo.value.code == 404
    assert excinfo.value.headers["Content-Type"] == "application/json"


def test_docs_gets_relaxed_csp_under_a_prefix(prefixed_server: str) -> None:
    """
    /docs still gets DOCS_CSP when the app runs under --root-path.

    Regression test: uvicorn's --root-path folds the prefix into
    scope["path"] itself (a request the app sees as "/docs" arrives with
    scope["path"] == "/prefix/docs"), so a middleware that compares against
    a bare "/docs" silently falls back to the strict CSP under any reverse
    proxy - a blank Swagger UI page with cdn.jsdelivr.net (blocked:csp)
    errors, even though the docs route itself serves 200 (FastAPI's own
    router already accounts for root_path).
    """
    with urllib.request.urlopen(f"{prefixed_server}/docs", timeout=5) as resp:
        assert resp.status == 200
        assert resp.headers["Content-Security-Policy"] == DOCS_CSP
