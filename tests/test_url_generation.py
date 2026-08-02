"""
The two kinds of URL the pages emit, and why each is shaped the way it is.

Rendering URLs - assets, form actions, in-site links - are root-relative
(`url_for(...).path`): the browser resolves them against the origin it
actually used, so the app never has to reconstruct its own public origin and
no proxy configuration can make it guess wrong.

The canonical link is absolute (bare `url_for`): it names the one address a
search engine should index, which is a different page on every host, so it
has to carry the scheme and host.

Both halves matter. Making the canonical link relative makes it useless;
making the asset URLs absolute makes them wrong on any deployment whose
proxy uvicorn has not been told to trust. See "URL generation" in
docs/ARCHITECTURE.md.
"""

import urllib.parse
import urllib.request

from .helpers import EmittedUrl, emitted_urls


def _page(base_url: str, path: str = "/") -> list[EmittedUrl]:
    """GET a page and return every URL it emits."""
    with urllib.request.urlopen(f"{base_url}{path}", timeout=5) as response:
        return emitted_urls(response.read().decode())


def _canonical(urls: list[EmittedUrl]) -> str:
    """Return the page's single canonical URL, asserting there is exactly one."""
    canonicals = [emitted.url for emitted in urls if emitted.is_canonical]
    assert len(canonicals) == 1, (
        f"expected exactly one canonical link, got {canonicals}"
    )
    return canonicals[0]


def test_rendering_urls_name_no_origin_so_a_proxy_cannot_break_them(
    server: str,
) -> None:
    """
    Nothing the browser must fetch carries a scheme or host.

    An absolute asset URL is only right when uvicorn believed the proxy's
    X-Forwarded-Proto, which it does only for UVICORN_FORWARDED_ALLOW_IPS peers
    (default 127.0.0.1, never the proxy in a container). Get that wrong and
    the URLs come out http:// on an https:// page, where the app's own CSP
    (style-src 'self') blocks them as cross-origin: the site renders
    unstyled, with a dead theme switch and a dead shout form. Root-relative
    URLs remove the guess, so the failure cannot happen.
    """
    absolute = [
        emitted.url
        for emitted in _page(server)
        if not emitted.is_canonical and emitted.names_an_origin
    ]
    assert not absolute, (
        "these URLs name an origin the app had to reconstruct from the"
        f" request, which breaks behind a TLS-terminating proxy: {absolute}"
    )


def test_rendering_urls_still_carry_the_root_path_prefix(
    prefixed_server: str,
) -> None:
    """
    Dropping the origin must not drop root_path.

    The other half of the guarantee above: a "simplification" that writes
    "css/style.css" by hand, or strips url_for entirely, would satisfy the
    no-origin rule and silently break every path-prefixed deployment.
    """
    urls = [emitted for emitted in _page(prefixed_server) if not emitted.is_canonical]
    assert urls, "the page emitted no rendering URLs at all - the page changed"
    for emitted in urls:
        assert emitted.url.startswith("/prefix/"), (
            f"<{emitted.tag}> emits {emitted.url}, which lost the root_path"
            " prefix - rendering URLs must be root-relative *and* prefixed"
        )


def test_canonical_link_is_absolute_so_crawlers_get_one_indexable_address(
    server: str,
) -> None:
    """
    The canonical link names a full origin, unlike every other URL here.

    "/" is a different page on every host that serves it, so a root-relative
    canonical link would tell a crawler nothing it did not already know.
    This is the URL the trusted-host allowlist protects
    (tests/test_trusted_hosts.py) and the one that needs the deployment's
    proxy headers configured to come out with the right scheme.
    """
    parts = urllib.parse.urlsplit(_canonical(_page(server)))
    assert parts.scheme, "the canonical link carries no scheme"
    assert parts.netloc, "the canonical link carries no host"


def test_canonical_link_carries_the_root_path_prefix(prefixed_server: str) -> None:
    """The indexable address of a prefixed deployment includes its prefix."""
    parts = urllib.parse.urlsplit(_canonical(_page(prefixed_server)))
    assert parts.path == "/prefix/", (
        f"the canonical link points at {parts.path}, which is outside the"
        " deployment's root path"
    )
