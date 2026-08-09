"""Application-factory and configuration isolation tests."""

import pytest
from starlette.routing import Mount, Route

from app.config import DEFAULT_MAX_BODY_BYTES, DEFAULT_TRUSTED_HOSTS, Settings
from app.factory import create_app
from app.middleware import DOCS_CSP, SECURITY_HEADERS
from app.observability import LogFormat
from tests.helpers import (
    body_limited_app,
    drive_get,
    framework_app,
    security_headers_app,
)


def test_factory_keeps_application_configurations_isolated() -> None:
    """Two configurations coexist without environment mutation or module reloads."""
    docs_settings = Settings(
        docs_enabled=True,
        trusted_hosts=("docs.example",),
        max_body_bytes=1_024,
    )
    production_settings = Settings(
        docs_enabled=False,
        trusted_hosts=("www.example",),
        max_body_bytes=2_048,
    )

    docs_app = create_app(docs_settings)
    production_app = create_app(production_settings)
    docs_framework = framework_app(docs_app)
    production_framework = framework_app(production_app)

    assert docs_framework is not production_framework
    assert docs_framework.state.settings is docs_settings
    assert production_framework.state.settings is production_settings
    docs_paths = {
        route.path
        for route in docs_framework.routes
        if isinstance(route, (Mount, Route))
    }
    production_paths = {
        route.path
        for route in production_framework.routes
        if isinstance(route, (Mount, Route))
    }
    assert {"/docs", "/openapi.json"} <= docs_paths
    assert {"/docs", "/openapi.json"}.isdisjoint(production_paths)
    assert security_headers_app(docs_app).docs_enabled is True
    assert security_headers_app(production_app).docs_enabled is False
    assert body_limited_app(docs_app).max_body_bytes == 1_024
    assert body_limited_app(production_app).max_body_bytes == 2_048

    docs_page = drive_get(docs_app, "/docs", host="docs.example")
    gated_page = drive_get(production_app, "/docs", host="www.example")
    assert docs_page.status == 200
    assert b'<div id="swagger-ui">' in docs_page.body
    assert docs_page.headers["content-security-policy"] == DOCS_CSP
    assert gated_page.status == 404
    assert (
        gated_page.headers["content-security-policy"]
        == SECURITY_HEADERS["Content-Security-Policy"]
    )

    # The schema gates together with the docs UI, at the request level too -
    # and its 404 carries the strict CSP, never the docs relaxation.
    schema = drive_get(docs_app, "/openapi.json", host="docs.example")
    gated_schema = drive_get(production_app, "/openapi.json", host="www.example")
    assert schema.status == 200
    assert gated_schema.status == 404
    assert (
        gated_schema.headers["content-security-policy"]
        == SECURITY_HEADERS["Content-Security-Policy"]
    )


def test_settings_load_and_normalize_environment_values() -> None:
    settings = Settings.from_env(
        {
            "WEBSITE_ENABLE_DOCS": "1",
            "WEBSITE_TRUSTED_HOSTS": " SITE.example, *.Internal.Example ",
            "WEBSITE_MAX_BODY_BYTES": "4096",
            "LOG_LEVEL": "debug",
            "LOG_FORMAT": "JSON",
        }
    )

    assert settings == Settings(
        docs_enabled=True,
        trusted_hosts=("site.example", "*.internal.example"),
        max_body_bytes=4_096,
        log_level="DEBUG",
        log_format=LogFormat.JSON,
    )


def test_settings_defaults_are_production_safe() -> None:
    assert Settings.from_env({}) == Settings(
        trusted_hosts=DEFAULT_TRUSTED_HOSTS,
        max_body_bytes=DEFAULT_MAX_BODY_BYTES,
    )


def test_from_env_names_the_variable_for_a_non_integer_body_cap() -> None:
    """The parse error names WEBSITE_MAX_BODY_BYTES, not just "invalid literal"."""
    with pytest.raises(ValueError, match=r"WEBSITE_MAX_BODY_BYTES.*'1MB'"):
        Settings.from_env({"WEBSITE_MAX_BODY_BYTES": "1MB"})


def test_from_env_rejects_an_unknown_log_format() -> None:
    """
    A misspelled rendering refuses to boot instead of falling back to text.

    Silently defaulting would ship human-readable lines to a pipeline that
    parses JSON, and the first sign of it would be a dashboard that quietly
    stopped matching - long after the deploy that caused it.
    """
    with pytest.raises(ValueError, match=r"LOG_FORMAT.*'structured'"):
        Settings.from_env({"LOG_FORMAT": "structured"})


@pytest.mark.parametrize("value", ["true", "yes", "on"])
def test_from_env_rejects_unrecognized_docs_flag(value: str) -> None:
    """WEBSITE_ENABLE_DOCS=true silently meaning *off* would be a footgun."""
    with pytest.raises(ValueError, match=rf"WEBSITE_ENABLE_DOCS.*{value!r}"):
        Settings.from_env({"WEBSITE_ENABLE_DOCS": value})


@pytest.mark.parametrize("value", ["0", ""])
def test_from_env_accepts_explicit_docs_off(value: str) -> None:
    """'0' and '' (a compose default that didn't resolve) both mean off."""
    assert Settings.from_env({"WEBSITE_ENABLE_DOCS": value}).docs_enabled is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"trusted_hosts": ("", " ")}, "trusted_hosts"),
        ({"max_body_bytes": 0}, "max_body_bytes"),
        ({"log_level": "verbose"}, "log level"),
    ],
)
def test_settings_reject_invalid_values(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        Settings(**overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "trusted_host",
    [
        "foo*bar",
        "*foo.example",
        "*.",
        "site.example:443",
        "https://site.example",
        "site.example/path",
        "site example",
        "site\x00example",
        "[::1]",
    ],
)
def test_settings_reject_invalid_trusted_host_patterns(trusted_host: str) -> None:
    """Every accepted host pattern is safe for Starlette to match."""
    with pytest.raises(ValueError, match=r"trusted_hosts/WEBSITE_TRUSTED_HOSTS"):
        Settings(trusted_hosts=(trusted_host,))
