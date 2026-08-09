"""
Guards for running behind a reverse proxy: the dev Caddy topology, and the image.

Two deployments of the same idea. The development half is Compose plus a
Caddy sidecar and a dedicated Uvicorn backend; the distribution half is the
published image. Both receive the same native UVICORN_* settings. The image's
configuration is exercised for real - no Docker in the dev container, so the
tests run its exec-form entrypoint with the environment defaults the
Dockerfile declares.
"""

import ipaddress
import os
import re
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest

from .conftest import SRC_DIR, next_test_port, run_server_command
from .helpers import (
    DEVCONTAINER_DIR,
    compose_config,
    compose_services,
    distribution_entrypoint,
    distribution_environment,
    emitted_urls,
)

REPO_ROOT = Path(__file__).parent.parent

REVERSE_PROXY_VARIABLES = {
    "WEBSITE_PROXY_HTTP_PORT",
    "WEBSITE_PROXY_HTTPS_PORT",
    "WEBSITE_PROXY_BACKEND_PORT",
    "UVICORN_ROOT_PATH",
}

UVICORN_PROXY_VARIABLES = {
    "UVICORN_ROOT_PATH",
    "UVICORN_PROXY_HEADERS",
    "UVICORN_FORWARDED_ALLOW_IPS",
}


def _example_environment() -> dict[str, str]:
    """Return uncommented key/value pairs from the committed example environment."""
    values = {}
    for line in (DEVCONTAINER_DIR / ".env.example").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value.strip('"')
    return values


def _assert_declared(environment: dict[str, str], names: set[str]) -> None:
    """
    Name the settings the example environment is missing, before any lookup.

    Every lookup below would otherwise raise a bare KeyError naming only the
    first missing variable, which reads as a broken test rather than an
    incomplete .env.example.
    """
    assert environment.keys() >= names, (
        f"example environment is missing {sorted(names - environment.keys())}"
    )


def test_reverse_proxy_example_environment_is_complete() -> None:
    """Every required proxy setting is documented with non-conflicting ports."""
    environment = _example_environment()
    _assert_declared(environment, REVERSE_PROXY_VARIABLES)

    root_path = environment["UVICORN_ROOT_PATH"]
    assert root_path.startswith("/")
    assert root_path != "/"
    assert not root_path.endswith("/")

    port_names = {
        "WEBSITE_EXTERNAL_PORT",
        "UVICORN_PORT",
        *(
            name
            for name in REVERSE_PROXY_VARIABLES
            if name.startswith("WEBSITE_PROXY_") and name.endswith("_PORT")
        ),
    }
    _assert_declared(environment, port_names)
    ports = [int(environment[name]) for name in port_names]
    assert len(ports) == len(set(ports)), "example environment reuses a port"

    # The whole inclusive test range must stay clear of the single ports -
    # a port between MIN and MAX collides even though no variable names it.
    _assert_declared(environment, {"WEBSITE_TEST_PORT_MIN", "WEBSITE_TEST_PORT_MAX"})
    test_port_min = int(environment["WEBSITE_TEST_PORT_MIN"])
    test_port_max = int(environment["WEBSITE_TEST_PORT_MAX"])
    assert test_port_min <= test_port_max, "example test port range is empty"
    assert not any(test_port_min <= port <= test_port_max for port in ports), (
        "example environment reuses a port inside the test range"
    )


def test_caddy_image_is_versioned_and_digest_pinned() -> None:
    """The added development dependency follows the repository's image policy."""
    image = compose_services()["caddy"]["image"]
    assert re.fullmatch(r"caddy:\d+\.\d+\.\d+-alpine@sha256:[0-9a-f]{64}", image)


def test_caddy_is_independent_and_proxy_backend_stays_private() -> None:
    """The proxy topology cannot alter direct development or expose its backend."""
    services = compose_services()
    master = services["master"]
    backend = services["proxy-backend"]
    caddy = services["caddy"]

    assert "depends_on" not in master
    assert "depends_on" not in backend
    assert "depends_on" not in caddy
    assert UVICORN_PROXY_VARIABLES.isdisjoint(master["environment"])
    assert backend["environment"].keys() >= UVICORN_PROXY_VARIABLES

    published_ports = [
        port for service in services.values() for port in service.get("ports", [])
    ]
    assert not any("WEBSITE_PROXY_BACKEND_PORT" in port for port in published_ports)


def test_reverse_proxy_trusted_ip_matches_caddys_pinned_address() -> None:
    """Uvicorn trusts exactly Caddy's pinned Compose-network address, not "*"."""
    compose = compose_config()
    services = compose["services"]
    trusted_ip = services["proxy-backend"]["environment"]["UVICORN_FORWARDED_ALLOW_IPS"]
    assert trusted_ip != "*"

    ((network_name, caddy_network),) = services["caddy"]["networks"].items()
    assert caddy_network["ipv4_address"] == trusted_ip

    subnet = compose["networks"][network_name]["ipam"]["config"][0]["subnet"]
    assert ipaddress.ip_address(trusted_ip) in ipaddress.ip_network(subnet)


def test_caddy_strips_configured_prefix_to_private_uvicorn_backend() -> None:
    """The Caddyfile and Compose environment agree on the proxy contract."""
    caddyfile = (DEVCONTAINER_DIR / "Caddyfile").read_text()
    assert "handle_path {$UVICORN_ROOT_PATH}/* {" in caddyfile
    assert "reverse_proxy proxy-backend:{$WEBSITE_PROXY_BACKEND_PORT}" in caddyfile
    assert "tls internal" in caddyfile
    assert "auto_https disable_redirects" in caddyfile


def test_caddy_caps_request_body_size() -> None:
    """
    The dev proxy enforces the same transport-level body cap as the app.

    Caddy's "1MB" counts 10^6 bytes, matching DEFAULT_MAX_BODY_BYTES in
    src/app/config.py - the proxy refuses oversized uploads before uvicorn
    sees them, and the in-app guard covers directly exposed containers.
    """
    caddyfile = (DEVCONTAINER_DIR / "Caddyfile").read_text()
    assert "request_body {" in caddyfile
    assert "max_size 1MB" in caddyfile


def test_caddy_compresses_responses() -> None:
    """
    The dev proxy compresses, because the app deliberately does not.

    Compression is CPU-bound work that would run on uvicorn's event loop, so
    it belongs to the proxy in the same way HSTS does - which means the dev
    topology is the only place the repository can show a production ingress
    what to do (see "Compression" in docs/ARCHITECTURE.md).
    """
    caddyfile = (DEVCONTAINER_DIR / "Caddyfile").read_text()
    assert "encode zstd gzip" in caddyfile


def test_compose_trusts_the_proxy_host() -> None:
    """The proxy backend's host allowlist includes Caddy's public site name."""
    environment = compose_services()["proxy-backend"]["environment"]
    trusted = environment["WEBSITE_TRUSTED_HOSTS"]
    assert "proxy.localhost" in trusted


def test_development_and_distribution_use_native_uvicorn_settings() -> None:
    """Development and production expose one server-configuration contract."""
    environment = distribution_environment()
    assert environment.keys() >= UVICORN_PROXY_VARIABLES
    assert environment["UVICORN_ROOT_PATH"] == ""
    assert environment["UVICORN_PROXY_HEADERS"] == "true"
    assert environment["UVICORN_FORWARDED_ALLOW_IPS"] == "127.0.0.1"
    assert distribution_entrypoint() == ["uvicorn", "app.main:app"]


@contextmanager
def _running_entrypoint(
    port: int, *extra_args: str, **overrides: str
) -> Generator[str]:
    """
    Run the distribution image's entrypoint locally, as Docker would run it.

    The environment is the image's own ENV defaults plus `overrides`, and
    deliberately not this process's: what the image ships is the whole point,
    and the dev container's ambient UVICORN_* variables would otherwise decide
    the outcome. PATH and PYTHONPATH stand in for the image's layout - the
    entrypoint calls the `uvicorn` console script (which, unlike `python -m`,
    puts nothing on sys.path) and the image's PYTHONPATH=/src is this repo's
    src/ here.
    """
    environment = {
        **distribution_environment(),
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(SRC_DIR),
        "UVICORN_PORT": str(port),
        **overrides,
    }
    with run_server_command(
        # --host, because the image binds 0.0.0.0 and a test server has no
        # business on this machine's other interfaces. That it takes effect at
        # all is the argument pass-through working.
        [*distribution_entrypoint(), "--host", "127.0.0.1", *extra_args],
        port,
        environment,
        cwd=REPO_ROOT,
    ) as base_url:
        yield base_url


def _canonical_link(base_url: str) -> str:
    """Return the homepage's canonical URL, requested as a TLS proxy would."""
    request = urllib.request.Request(
        f"{base_url}/", headers={"X-Forwarded-Proto": "https"}
    )
    with urllib.request.urlopen(request, timeout=5) as resp:
        html = resp.read().decode()
    canonical = [emitted.url for emitted in emitted_urls(html) if emitted.is_canonical]
    assert len(canonical) == 1, f"expected one canonical link, found {canonical}"
    return canonical[0]


@pytest.mark.parametrize(
    ("trusted_ips", "proxy_headers", "expected_scheme"),
    [
        ("127.0.0.1", "true", "https"),
        ("10.0.0.1", "true", "http"),
        ("127.0.0.1", "false", "http"),
    ],
)
def test_image_honors_forwarded_proto_from_trusted_peers_only(
    trusted_ips: str, proxy_headers: str, expected_scheme: str
) -> None:
    """
    Native Uvicorn settings decide whether and whose forwarded header is believed.

    Both halves are needed: that the header is honored at all only proves
    uvicorn's default (which happens to be the loopback this test connects
    from), so the second case - the same request from a peer the variable does
    not name - is what proves the variable is wired to the flag rather than
    ignored. An unbelieved header leaves an HTTPS site advertising an http://
    canonical link (see "URL generation" in docs/ARCHITECTURE.md).
    """
    port = next_test_port()
    with _running_entrypoint(
        port,
        UVICORN_FORWARDED_ALLOW_IPS=trusted_ips,
        UVICORN_PROXY_HEADERS=proxy_headers,
    ) as base_url:
        canonical = _canonical_link(base_url)
    assert canonical == f"{expected_scheme}://127.0.0.1:{port}/"


def test_image_root_path_comes_from_the_environment_or_the_arguments() -> None:
    """
    UVICORN_ROOT_PATH prefixes generated URLs, and a CLI argument overrides it.

    Uvicorn takes the last occurrence of a repeated option, which is what
    makes the appended flag win - how a deployment overrides any default this
    image ships without rebuilding it.
    """
    port = next_test_port()
    with _running_entrypoint(
        port, "--root-path", "/argument", UVICORN_ROOT_PATH="/environment"
    ) as base_url:
        canonical = _canonical_link(base_url)
    assert canonical == f"https://127.0.0.1:{port}/argument/"

    port = next_test_port()
    with _running_entrypoint(port, UVICORN_ROOT_PATH="/environment") as base_url:
        canonical = _canonical_link(base_url)
    assert canonical == f"https://127.0.0.1:{port}/environment/"
