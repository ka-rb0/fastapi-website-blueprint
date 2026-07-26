"""Application-factory and configuration isolation tests."""

import asyncio

import pytest
from fastapi import FastAPI
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Message, Scope

from app.config import DEFAULT_MAX_BODY_BYTES, DEFAULT_TRUSTED_HOSTS, Settings
from app.factory import create_app
from app.middleware import (
    DOCS_CSP,
    SECURITY_HEADERS,
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
)


def _framework_app(application: ASGIApp) -> FastAPI:
    """Return the FastAPI instance after asserting the production wrapper order."""
    assert isinstance(application, SecurityHeadersMiddleware)
    assert isinstance(application.app, BodySizeLimitMiddleware)
    assert isinstance(application.app.app, FastAPI)
    return application.app.app


def _get(
    application: ASGIApp, path: str, *, host: str
) -> tuple[int, dict[str, str], bytes]:
    """Drive one GET through an ASGI app without a server or global environment."""
    messages: list[Message] = []
    request_sent = False

    async def receive() -> Message:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", host.encode())],
        "server": (host, 80),
        "client": ("127.0.0.1", 12345),
    }
    asyncio.run(application(scope, receive, send))

    start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    headers = {
        name.decode().lower(): value.decode() for name, value in start["headers"]
    }
    return start["status"], headers, body


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
    assert isinstance(docs_app, SecurityHeadersMiddleware)
    assert isinstance(production_app, SecurityHeadersMiddleware)
    docs_framework = _framework_app(docs_app)
    production_framework = _framework_app(production_app)

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
    assert docs_app.docs_enabled is True
    assert production_app.docs_enabled is False
    assert isinstance(docs_app.app, BodySizeLimitMiddleware)
    assert isinstance(production_app.app, BodySizeLimitMiddleware)
    assert docs_app.app.max_body_bytes == 1_024
    assert production_app.app.max_body_bytes == 2_048

    docs_status, docs_headers, docs_body = _get(docs_app, "/docs", host="docs.example")
    production_status, production_headers, _ = _get(
        production_app, "/docs", host="www.example"
    )
    assert docs_status == 200
    assert b'<div id="swagger-ui">' in docs_body
    assert docs_headers["content-security-policy"] == DOCS_CSP
    assert production_status == 404
    assert (
        production_headers["content-security-policy"]
        == SECURITY_HEADERS["Content-Security-Policy"]
    )

    # The schema gates together with the docs UI, at the request level too -
    # and its 404 carries the strict CSP, never the docs relaxation.
    schema_status, _, _ = _get(docs_app, "/openapi.json", host="docs.example")
    gated_status, gated_headers, _ = _get(
        production_app, "/openapi.json", host="www.example"
    )
    assert schema_status == 200
    assert gated_status == 404
    assert (
        gated_headers["content-security-policy"]
        == SECURITY_HEADERS["Content-Security-Policy"]
    )


def test_settings_load_and_normalize_environment_values() -> None:
    settings = Settings.from_env(
        {
            "WEBSITE_ENABLE_DOCS": "1",
            "WEBSITE_TRUSTED_HOSTS": " site.example, *.internal.example ",
            "WEBSITE_MAX_BODY_BYTES": "4096",
            "LOG_LEVEL": "debug",
        }
    )

    assert settings == Settings(
        docs_enabled=True,
        trusted_hosts=("site.example", "*.internal.example"),
        max_body_bytes=4_096,
        log_level="DEBUG",
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
