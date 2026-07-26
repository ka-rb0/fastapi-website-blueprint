"""Shared in-process helpers for tests that drive the factory-built stack."""

from fastapi import FastAPI

from app.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware


def framework_app(application: SecurityHeadersMiddleware) -> FastAPI:
    """
    Return the FastAPI instance after asserting the production wrapper order.

    The isinstance chain is itself a test: header stamp outermost, body guard
    inside it, framework innermost (see "Composition root" in
    docs/ARCHITECTURE.md). Every in-process test unwraps through here, so a
    reordered stack fails loudly everywhere at once.
    """
    assert isinstance(application, SecurityHeadersMiddleware)
    assert isinstance(application.app, BodySizeLimitMiddleware)
    assert isinstance(application.app.app, FastAPI)
    return application.app.app
