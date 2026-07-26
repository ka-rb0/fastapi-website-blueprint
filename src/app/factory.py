"""Application composition root."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .exceptions import register_exception_handlers
from .lifecycle import lifespan
from .middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from .routers import api_router, create_pages_router
from .templating import STATIC_DIR, create_templates

APP_TITLE = "FastAPI Website Blueprint"


def create_app(settings: Settings) -> SecurityHeadersMiddleware:
    """Build a fully configured, independently testable ASGI application."""
    templates = create_templates()
    fastapi_app = FastAPI(
        title=APP_TITLE,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        redoc_url=None,
    )
    fastapi_app.state.settings = settings
    fastapi_app.state.templates = templates

    fastapi_app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=list(settings.trusted_hosts)
    )
    fastapi_app.include_router(create_pages_router(templates))
    fastapi_app.include_router(api_router)
    register_exception_handlers(fastapi_app, templates)

    # Mount assets last so application routes always take precedence.
    fastapi_app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")

    body_limited_app = BodySizeLimitMiddleware(
        fastapi_app, max_body_bytes=settings.max_body_bytes
    )
    return SecurityHeadersMiddleware(
        body_limited_app, docs_enabled=settings.docs_enabled
    )
