"""
Guards for deployment under a URL prefix.

Against `prefixed_server` (uvicorn --root-path /prefix, see conftest.py):
the browser resolves a page's links against the site's *public* URL, so a
hand-written /static/css/theme.css would escape the prefix and miss the app
entirely. The templates generate every URL with url_for (which carries
root_path) and js/shout.js reads the API endpoint from the form's rendered
action attribute - these tests fetch the live pages and assert the prefix
landed everywhere a URL is emitted.

Rendering URLs are root-relative (`url_for(...).path`, see base.html), so
the assertions below match `/prefix/...` rather than a full origin. Which
URLs carry an origin at all is decided in tests/test_url_generation.py;
these tests only care that the prefix reached every one of them.
"""

import re
import urllib.error
import urllib.request

import pytest

from app.middleware import DOCS_COOP, DOCS_CSP
from app.templating import STATIC_URL_PATH

# Every static asset the pages reference, by path under the static mount.
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
        # Quoted, so this matches a whole attribute value: an unquoted
        # substring check would also pass on http://elsewhere/prefix/....
        assert f'"/prefix{STATIC_URL_PATH}/{asset}"' in html, (
            f"{asset} is not referenced under the /prefix root path"
        )


def test_shout_form_action_carries_prefix(prefixed_server: str) -> None:
    """The form metadata js/shout.js submits through points inside the prefix."""
    html = _get_html(f"{prefixed_server}/")
    match = re.search(r'<form\b[^>]*\bid="shout-form"[^>]*>', html, re.DOTALL)
    assert match, '<form id="shout-form" ...> not found in the rendered homepage'
    action = re.search(r'\baction="([^"]*)"', match.group(0))
    assert action, "the shout form carries no action attribute"
    assert action.group(1) == "/prefix/api/shout"


def test_not_found_home_link_carries_prefix(prefixed_server: str) -> None:
    """The 404 page's way home leads to the prefixed site root."""
    html = _get_html(f"{prefixed_server}/no/such/page", expected_status=404)
    assert 'href="/prefix/"' in html


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


def test_docs_gets_relaxed_browser_policies_under_a_prefix(
    prefixed_server: str,
) -> None:
    """
    /docs still gets its browser-policy exceptions under --root-path.

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
        assert resp.headers["Cross-Origin-Opener-Policy"] == DOCS_COOP
