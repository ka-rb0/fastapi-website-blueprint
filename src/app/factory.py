"""Application composition root."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .exceptions import register_exception_handlers
from .lifecycle import create_lifespan
from .middleware import (
    BodySizeLimitMiddleware,
    HostValidationMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)
from .routers import PROBE_PATHS, api_router, create_pages_router, probes_router
from .templating import STATIC_DIR, create_templates

APP_TITLE = "FastAPI Website Blueprint"


def create_app(settings: Settings) -> RequestIDMiddleware:
    """
    Build a fully configured, independently testable application stack.

    Returns the concrete outermost wrapper, not an opaque ASGIApp: the classes
    are public API, and the concrete types are what let tests and embedding
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

    # The probe routes are exempt: an orchestrator probes a pod by its own IP,
    # which no allowlist can name in advance (see HostValidationMiddleware and
    # "Trusted hosts" in docs/ARCHITECTURE.md).
    fastapi_app.add_middleware(
        HostValidationMiddleware,
        allowed_hosts=settings.trusted_hosts,
        exempt_paths=PROBE_PATHS,
    )
    fastapi_app.include_router(create_pages_router(templates))
    fastapi_app.include_router(api_router)
    fastapi_app.include_router(probes_router)
    register_exception_handlers(fastapi_app, templates)

    # Mount assets last so application routes always take precedence. No
    # html=True: its index.html/404.html special-casing belonged to an
    # all-static frontend - misses must raise 404s that the branded handler
    # (see app.exceptions) turns into the branded page.
    fastapi_app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")

    # Wrapper order is load-bearing - correlation outermost, so nothing below
    # can log or answer without an ID, then headers, so even the body guard's
    # 413s are stamped. See "Composition root" in docs/ARCHITECTURE.md.
    body_limited_app = BodySizeLimitMiddleware(
        fastapi_app, max_body_bytes=settings.max_body_bytes
    )
    header_stamped_app = SecurityHeadersMiddleware(
        body_limited_app, docs_enabled=settings.docs_enabled
    )
    return RequestIDMiddleware(header_stamped_app)
