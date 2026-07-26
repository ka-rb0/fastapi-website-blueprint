"""Guards for the optional development Caddy topology."""

import ipaddress
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).parent.parent
DEVCONTAINER_DIR = REPO_ROOT / ".devcontainer"

REVERSE_PROXY_VARIABLES = {
    "WEBSITE_EXTERNAL_HTTP_PORT_WITH_REVERSE_PROXY",
    "WEBSITE_EXTERNAL_HTTPS_PORT_WITH_REVERSE_PROXY",
    "WEBSITE_INTERNAL_PORT_WITH_REVERSE_PROXY",
    "WEBSITE_REVERSE_PROXY_ROOT_PATH",
}


def _example_environment() -> dict[str, str]:
    """Return uncommented key/value pairs from the committed example environment."""
    values = {}
    for line in (DEVCONTAINER_DIR / ".env.example").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value.strip('"')
    return values


def test_reverse_proxy_example_environment_is_complete() -> None:
    """Every required proxy setting is documented with non-conflicting ports."""
    environment = _example_environment()
    assert environment.keys() >= REVERSE_PROXY_VARIABLES

    root_path = environment["WEBSITE_REVERSE_PROXY_ROOT_PATH"]
    assert root_path.startswith("/")
    assert root_path != "/"
    assert not root_path.endswith("/")

    port_names = {
        "WEBSITE_EXTERNAL_PORT",
        "WEBSITE_INTERNAL_PORT",
        "WEBSITE_TEST_PORT",
        *(
            name
            for name in REVERSE_PROXY_VARIABLES
            if name.endswith("PORT_WITH_REVERSE_PROXY")
        ),
    }
    ports = [int(environment[name]) for name in port_names]
    assert len(ports) == len(set(ports)), "example environment reuses a port"


def _compose() -> dict[str, Any]:
    """
    Parse docker-compose.yml structurally.

    PyYAML is a declared dependency (see pyproject.toml) specifically so this
    file can assert on the parsed config - service names, keys, image
    strings - instead of raw text, which stays correct across reordering or
    reformatting that raw text wouldn't survive.
    """
    compose: dict[str, Any] = yaml.safe_load(
        (DEVCONTAINER_DIR / "docker-compose.yml").read_text()
    )
    return compose


def _compose_services() -> dict[str, Any]:
    """Return docker-compose.yml's `services` mapping."""
    services: dict[str, Any] = _compose()["services"]
    return services


def test_caddy_image_is_versioned_and_digest_pinned() -> None:
    """The added development dependency follows the repository's image policy."""
    image = _compose_services()["caddy"]["image"]
    assert re.fullmatch(r"caddy:\d+\.\d+\.\d+-alpine@sha256:[0-9a-f]{64}", image)


def test_caddy_is_independent_and_proxy_backend_stays_private() -> None:
    """Removing Caddy cannot break master, and its Uvicorn port is not published."""
    services = _compose_services()
    master = services["master"]
    caddy = services["caddy"]

    assert "depends_on" not in master
    assert "depends_on" not in caddy
    assert "WEBSITE_INTERNAL_PORT_WITH_REVERSE_PROXY" in master["environment"]
    assert "WEBSITE_REVERSE_PROXY_ROOT_PATH" in master["environment"]

    published_ports = [
        port for service in services.values() for port in service.get("ports", [])
    ]
    assert not any(
        "WEBSITE_INTERNAL_PORT_WITH_REVERSE_PROXY" in port for port in published_ports
    )


def test_reverse_proxy_trusted_ip_matches_caddys_pinned_address() -> None:
    """Uvicorn trusts exactly Caddy's pinned Compose-network address, not "*"."""
    compose = _compose()
    services = compose["services"]
    trusted_ip = services["master"]["environment"]["WEBSITE_REVERSE_PROXY_TRUSTED_IP"]
    assert trusted_ip != "*"

    ((network_name, caddy_network),) = services["caddy"]["networks"].items()
    assert caddy_network["ipv4_address"] == trusted_ip

    subnet = compose["networks"][network_name]["ipam"]["config"][0]["subnet"]
    assert ipaddress.ip_address(trusted_ip) in ipaddress.ip_network(subnet)


def test_caddy_strips_configured_prefix_to_second_uvicorn_listener() -> None:
    """The Caddyfile and Compose environment agree on the proxy contract."""
    caddyfile = (DEVCONTAINER_DIR / "Caddyfile").read_text()
    assert "handle_path {$WEBSITE_REVERSE_PROXY_ROOT_PATH}/* {" in caddyfile
    assert (
        "reverse_proxy master:{$WEBSITE_INTERNAL_PORT_WITH_REVERSE_PROXY}" in caddyfile
    )
    assert "tls internal" in caddyfile
    assert "auto_https disable_redirects" in caddyfile


def test_caddy_caps_request_body_size() -> None:
    """
    The dev proxy enforces the same transport-level body cap as the app.

    Caddy's "1MB" counts 10^6 bytes, matching MAX_BODY_BYTES' default in
    src/app/main.py - the proxy refuses oversized uploads before uvicorn
    sees them, and the in-app guard covers directly exposed containers.
    """
    caddyfile = (DEVCONTAINER_DIR / "Caddyfile").read_text()
    assert "request_body {" in caddyfile
    assert "max_size 1MB" in caddyfile


def test_compose_trusts_the_proxy_host() -> None:
    """The dev container's host allowlist includes Caddy's public site name."""
    environment = _compose_services()["master"]["environment"]
    trusted = environment["WEBSITE_TRUSTED_HOSTS"]
    assert "proxy.localhost" in trusted
