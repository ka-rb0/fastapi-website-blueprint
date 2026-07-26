"""
Host-header validation, against the live servers from conftest.py.

The templates build absolute URLs with url_for, which trusts the request's
Host header - so TrustedHostMiddleware (see TRUSTED_HOSTS in src/app/main.py)
must reject hosts outside the allowlist before anything is rendered, or an
attacker-chosen Host would be reflected into every generated URL.
"""

import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import pytest

from app.main import SECURITY_HEADERS


def _get_with_host(url: str, host: str) -> urllib.request.Request:
    """Build (not send) a GET whose Host header is `host`, not the URL's."""
    return urllib.request.Request(url, headers={"Host": host})


class _UrlAttributeCollector(HTMLParser):
    """Collect every URL-bearing attribute value (href/src/action) of a page."""

    _URL_ATTRIBUTES = frozenset({"action", "href", "src"})

    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.urls += [
            value
            for name, value in attrs
            if name in self._URL_ATTRIBUTES and value is not None
        ]


def _generated_origins(html: str) -> set[tuple[str, str]]:
    """
    Return the (scheme, host:port) origin of every absolute URL the page emits.

    Parsed with urlsplit rather than matched as a substring of the page:
    `"http://site.example/" in html` also passes on a URL that merely
    *contains* the trusted host somewhere else in it - say
    http://attacker.example/?next=http://site.example/ - so it would not
    actually prove the pages were built for the trusted host. That is the
    bypass CodeQL reports as py/incomplete-url-substring-sanitization ("the
    string http://site.example/ may be at an arbitrary position in the
    sanitized URL"); comparing parsed origins is the check it asks for.
    """
    collector = _UrlAttributeCollector()
    collector.feed(html)
    origins = set()
    for url in collector.urls:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme or parts.netloc:  # relative URLs carry no host to check
            origins.add((parts.scheme, parts.netloc))
    return origins


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_default_allowlist_accepts_local_hosts(server: str, host: str) -> None:
    """The out-of-the-box allowlist serves local development requests."""
    with urllib.request.urlopen(_get_with_host(server, host), timeout=5) as resp:
        assert resp.status == 200


def test_unknown_host_rejected_before_rendering(server: str) -> None:
    """
    A request with an untrusted Host gets a 400 and no rendered page.

    Rendering would reflect the attacker-chosen host into url_for-generated
    asset and form URLs - the body must not contain it.
    """
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(_get_with_host(server, "attacker.example"), timeout=5)
    assert excinfo.value.code == 400
    assert "attacker.example" not in excinfo.value.read().decode()


def test_rejection_carries_security_headers(server: str) -> None:
    """
    The 400 is still stamped with every security header.

    TrustedHostMiddleware sits inside the framework stack, but
    SecurityHeadersMiddleware wraps outside it - its rejections are
    responses like any other.
    """
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(_get_with_host(server, "attacker.example"), timeout=5)
    for name, value in SECURITY_HEADERS.items():
        assert excinfo.value.headers[name] == value


def test_configured_public_host_accepted(trusted_hosts_server: str) -> None:
    """
    WEBSITE_TRUSTED_HOSTS admits the deployment's public host name.

    site.example plays the Host a reverse proxy would forward; every URL the
    page generates carries it - reflection is fine once the host is trusted.
    """
    request = _get_with_host(trusted_hosts_server, "site.example")
    with urllib.request.urlopen(request, timeout=5) as resp:
        assert resp.status == 200
        origins = _generated_origins(resp.read().decode())
    assert origins == {("http", "site.example")}, (
        f"the page's generated URLs point at {sorted(origins)}, "
        "not only at the trusted host"
    )


def test_configured_allowlist_replaces_default(trusted_hosts_server: str) -> None:
    """WEBSITE_TRUSTED_HOSTS replaces the default - it doesn't extend it."""
    request = _get_with_host(trusted_hosts_server, "localhost")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=5)
    assert excinfo.value.code == 400
