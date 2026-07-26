"""Application composition root."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .exceptions import register_exception_handlers
from .lifecycle import create_lifespan
from .middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from .routers import api_router, create_pages_router
from .templating import STATIC_DIR, create_templates

APP_TITLE = "FastAPI Website Blueprint"


def create_app(settings: Settings) -> SecurityHeadersMiddleware:
    """
    Build a fully configured, independently testable application stack.

    Returns the concrete outermost wrapper, not an opaque ASGIApp: the class
    is public API, and the concrete type is what lets tests and embedding
    code unwrap to the FastAPI instance without guessing at private
    attributes (see framework_app in tests/helpers.py).
    """
    templates = create_templates()
    fastapi_app = FastAPI(
        title=APP_TITLE,
        lifespan=create_lifespan(settings),
        # The docs UI, its schema and ReDoc gate together as one development
        # tool - see "Interactive docs gating" in docs/ARCHITECTURE.md.
        docs_url="/docs" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        redoc_url=None,
    )
    # Runtime code receives these through closures; state is the
    # introspection point for tests and embedding code.
    fastapi_app.state.settings = settings
    fastapi_app.state.templates = templates

    fastapi_app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=list(settings.trusted_hosts)
    )
    fastapi_app.include_router(create_pages_router(templates))
    fastapi_app.include_router(api_router)
    register_exception_handlers(fastapi_app, templates)

    # Mount assets last so application routes always take precedence. No
    # html=True: its index.html/404.html special-casing belonged to an
    # all-static frontend - misses must raise 404s that the branded handler
    # (see app.exceptions) turns into the branded page.
    fastapi_app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")

    # Wrapper order is load-bearing - headers outermost, so even the body
    # guard's 413s are stamped. See "Composition root" in docs/ARCHITECTURE.md.
    body_limited_app = BodySizeLimitMiddleware(
        fastapi_app, max_body_bytes=settings.max_body_bytes
    )
    return SecurityHeadersMiddleware(
        body_limited_app, docs_enabled=settings.docs_enabled
    )
