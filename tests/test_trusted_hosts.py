"""
Host-header validation, against the live servers from conftest.py.

The homepage's canonical link is absolute (see tests/test_url_generation.py),
and url_for builds it from the request's Host header - so an unlisted Host
would be reflected into the address this site tells search engines to index.
TrustedHostMiddleware (configured in src/app/factory.py) rejects those
requests before anything is rendered.

The rest of the page carries no origin at all, so the canonical link is both
the reason this guard exists and the only place its absence would show.
"""

import urllib.error
import urllib.parse
import urllib.request

import pytest

from app.middleware import SECURITY_HEADERS

from .helpers import emitted_urls


def _get_with_host(url: str, host: str) -> urllib.request.Request:
    """Build (not send) a GET whose Host header is `host`, not the URL's."""
    return urllib.request.Request(url, headers={"Host": host})


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
    origins = set()
    for emitted in emitted_urls(html):
        parts = urllib.parse.urlsplit(emitted.url)
        if parts.scheme or parts.netloc:  # root-relative URLs name no origin
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

    The rejection happens before rendering, so the attacker-chosen host
    reaches no template and lands in no canonical link - the body must not
    contain it.
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


def test_only_a_trusted_host_reaches_the_canonical_link(
    trusted_hosts_server: str,
) -> None:
    """
    The trusted host is the only origin a rendered page names.

    WEBSITE_TRUSTED_HOSTS admits the deployment's public host name, and
    site.example plays the Host a reverse proxy forwards. Reflecting it is
    the point - the canonical link has to name the site's real address - and
    is safe precisely because the allowlist decided which hosts get that far.
    The set comparison also pins the other half: no *second* origin sneaks
    into the page, so a future absolute URL cannot quietly escape this guard.
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
