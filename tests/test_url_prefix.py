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
