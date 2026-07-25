"""Guards for the optional development Caddy topology."""

import re
from pathlib import Path

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


def test_caddy_image_is_versioned_and_digest_pinned() -> None:
    """The added development dependency follows the repository's image policy."""
    compose = (DEVCONTAINER_DIR / "docker-compose.yml").read_text()
    assert re.search(
        r"^\s*image: caddy:\d+\.\d+\.\d+-alpine@sha256:[0-9a-f]{64}$",
        compose,
        re.MULTILINE,
    )


def test_caddy_is_independent_and_proxy_backend_stays_private() -> None:
    """Removing Caddy cannot break master, and its Uvicorn port is not published."""
    compose = (DEVCONTAINER_DIR / "docker-compose.yml").read_text()
    master, remainder = compose.split("\n  caddy:\n", 1)
    caddy, _ = remainder.split("\nnetworks:\n", 1)

    assert "depends_on:" not in master
    assert "depends_on:" not in caddy
    assert "WEBSITE_INTERNAL_PORT_WITH_REVERSE_PROXY" in master
    assert "WEBSITE_REVERSE_PROXY_ROOT_PATH" in master
    assert ":${WEBSITE_INTERNAL_PORT_WITH_REVERSE_PROXY}" not in compose


def test_caddy_strips_configured_prefix_to_second_uvicorn_listener() -> None:
    """The Caddyfile and Compose environment agree on the proxy contract."""
    caddyfile = (DEVCONTAINER_DIR / "Caddyfile").read_text()
    assert "handle_path {$WEBSITE_REVERSE_PROXY_ROOT_PATH}/* {" in caddyfile
    assert (
        "reverse_proxy master:{$WEBSITE_INTERNAL_PORT_WITH_REVERSE_PROXY}" in caddyfile
    )
    assert "tls internal" in caddyfile
    assert "auto_https disable_redirects" in caddyfile
