"""
Host-header validation, against the live servers from conftest.py.

The templates build absolute URLs with url_for, which trusts the request's
Host header - so TrustedHostMiddleware (see TRUSTED_HOSTS in src/app/main.py)
must reject hosts outside the allowlist before anything is rendered, or an
attacker-chosen Host would be reflected into every generated URL.
"""

import urllib.error
import urllib.request

import pytest

from app.main import SECURITY_HEADERS


def _get_with_host(url: str, host: str) -> urllib.request.Request:
    """Build (not send) a GET whose Host header is `host`, not the URL's."""
    return urllib.request.Request(url, headers={"Host": host})


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

    site.example plays the Host a reverse proxy would forward; the URLs the
    page generates carry it - reflection is fine once the host is trusted.
    """
    request = _get_with_host(trusted_hosts_server, "site.example")
    with urllib.request.urlopen(request, timeout=5) as resp:
        assert resp.status == 200
        assert "http://site.example/" in resp.read().decode()


def test_configured_allowlist_replaces_default(trusted_hosts_server: str) -> None:
    """WEBSITE_TRUSTED_HOSTS replaces the default - it doesn't extend it."""
    request = _get_with_host(trusted_hosts_server, "localhost")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=5)
    assert excinfo.value.code == 400
