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

import json
import urllib.error
import urllib.request

import pytest

from app.middleware import SECURITY_HEADERS
from app.routers import PROBE_PATHS
from app.routers.probes import LIVENESS_PATH

from .helpers import emitted_urls

# An address a probe would use and no allowlist could contain: the pod IP a
# Kubernetes httpGet probe sends as Host, assigned when the pod is scheduled.
PROBE_HOST = "10.244.1.37"


def _get_with_host(url: str, host: str) -> urllib.request.Request:
    """Build (not send) a GET whose Host header is `host`, not the URL's."""
    return urllib.request.Request(url, headers={"Host": host})


def _generated_origins(html: str) -> set[tuple[str, str]]:
    """
    Return the (scheme, host:port) origin of every absolute URL the page emits.

    Parsed (EmittedUrl.origin) rather than matched as a substring of the
    page: `"http://site.example/" in html` also passes on a URL that merely
    *contains* the trusted host somewhere else in it - say
    http://attacker.example/?next=http://site.example/ - so it would not
    actually prove the pages were built for the trusted host. That is the
    bypass CodeQL reports as py/incomplete-url-substring-sanitization ("the
    string http://site.example/ may be at an arbitrary position in the
    sanitized URL"); comparing parsed origins is the check it asks for.
    """
    return {emitted.origin for emitted in emitted_urls(html) if emitted.names_an_origin}


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


def test_host_matching_is_case_insensitive(trusted_hosts_server: str) -> None:
    """DNS host names match regardless of their presentation case."""
    request = _get_with_host(trusted_hosts_server, "SITE.EXAMPLE")
    with urllib.request.urlopen(request, timeout=5) as resp:
        assert resp.status == 200
        origins = _generated_origins(resp.read().decode())
    assert origins == {("http", "site.example")}


def test_configured_allowlist_replaces_default(trusted_hosts_server: str) -> None:
    """WEBSITE_TRUSTED_HOSTS replaces the default - it doesn't extend it."""
    request = _get_with_host(trusted_hosts_server, "localhost")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=5)
    assert excinfo.value.code == 400


@pytest.mark.parametrize("path", PROBE_PATHS)
def test_probes_answer_a_host_the_allowlist_cannot_name(
    trusted_hosts_server: str, path: str
) -> None:
    """
    Every probe route answers whatever Host a probe sends.

    PROBE_HOST plays a Kubernetes httpGet probe, which addresses the pod by
    its own IP: an address assigned at scheduling time, so no
    WEBSITE_TRUSTED_HOSTS value could contain it and every pod would fail its
    liveness check into CrashLoopBackOff. The routes are exempt from the
    allowlist instead (see HostValidationMiddleware) - they can be, because
    they reflect nothing of the request back.

    Parametrized over the whole tuple because the exemption is granted to the
    whole tuple: a route added to it without this property would be the leak.
    """
    request = _get_with_host(f"{trusted_hosts_server}{path}", PROBE_HOST)
    with urllib.request.urlopen(request, timeout=5) as resp:
        assert resp.status == 200
        assert json.loads(resp.read()) == {"status": "ok"}


@pytest.mark.parametrize("path", PROBE_PATHS)
def test_probe_exemption_survives_a_root_path(prefixed_server: str, path: str) -> None:
    """
    The probes still answer when the app runs under a prefix.

    uvicorn's --root-path folds the prefix into scope["path"], so an
    exemption compared against a bare "/livez" would silently stop applying
    behind exactly the reverse proxy that makes the probe necessary. The
    request goes to the unprefixed path, as a probe addressing the container
    directly sends it.
    """
    request = _get_with_host(f"{prefixed_server}{path}", PROBE_HOST)
    with urllib.request.urlopen(request, timeout=5) as resp:
        assert resp.status == 200


@pytest.mark.parametrize("path", ["/", "/api/shout", f"{LIVENESS_PATH}/"])
def test_the_exemption_reaches_no_further_than_the_probe_routes(
    trusted_hosts_server: str, path: str
) -> None:
    """
    Every other path - including a probe's trailing-slash form - is guarded.

    The trailing slash is the case the exact comparison buys: normalizing the
    path before matching would exempt a request the router answers with a
    redirect whose Location is built from the untrusted Host.
    """
    request = _get_with_host(f"{trusted_hosts_server}{path}", PROBE_HOST)
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=5)
    assert excinfo.value.code == 400
