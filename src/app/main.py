"""
FastAPI Website Blueprint server.

Serves the static frontend from src/app/static and the /api endpoints.

Run with:  uvicorn app.main:app --host 0.0.0.0 --port $WEBSITE_INTERNAL_PORT --reload
"""

import logging
import os
import posixpath
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Logging is configured at startup, not import: importing app.main (tests,
    # tooling) must not reconfigure the process-wide root logger.
    # .upper() so LOG_LEVEL=debug works too - logging only accepts upper-case names
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
    logger.info("Serving static files from %s", STATIC_DIR)
    yield


# The interactive API docs are a development tool: /docs only exists when
# WEBSITE_ENABLE_DOCS=1 (the devcontainer sets it; production should not).
# The page needs CSP exceptions - see DOCS_CSP below - so keeping it out of
# production also keeps production on the strict policy everywhere.
DOCS_ENABLED = os.environ.get("WEBSITE_ENABLE_DOCS") == "1"

fastapi_app = FastAPI(
    title="FastAPI Website Blueprint",
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    # The machine-readable schema is a dev tool just like the docs UI that
    # consumes it, so it gates on the same flag.
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
    # No ReDoc: one docs UI is enough, and each one is its own set of CSP
    # exceptions.
    redoc_url=None,
)

# Defense-in-depth headers on every response (static files and API alike).
# The CSP allows only same-origin resources, which matches the self-contained
# frontend (no CDNs, no inline scripts - even the pre-paint theme script is a
# file, js/theme-init.js, for exactly this reason). Extend the CSP when you
# add external resources; don't drop it.
# No Strict-Transport-Security here on purpose: HSTS belongs at the
# TLS-terminating reverse proxy - the app itself only ever speaks plain HTTP.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self'; "
        "connect-src 'self'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    # Legacy complement to the CSP's frame-ancestors for pre-CSP2 browsers.
    "X-Frame-Options": "DENY",
    # The modern browser default, made explicit for older browsers whose
    # default (no-referrer-when-downgrade) leaks full URLs cross-origin.
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # A cross-origin page that opened this site (or was opened by it) gets no
    # window handle: logged-in pages can't be tab-nabbed or probed for
    # XS-Leaks through window.opener.
    "Cross-Origin-Opener-Policy": "same-origin",
    # No cross-origin embedding of this site's responses: authenticated,
    # per-user data can't be pulled into another origin's process via
    # <img>/<script> inclusion (Spectre-class side channels).
    "Cross-Origin-Resource-Policy": "same-origin",
    # The frontend uses none of these; opt out so embedded content can't either.
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

# The one exception to the strict CSP - and the pattern to copy when a page
# of yours needs one. FastAPI's generated /docs page loads Swagger UI from
# cdn.jsdelivr.net, boots it with an inline script, and the UI injects inline
# styles and data: images while rendering; its favicon comes from
# fastapi.tiangolo.com. With dev tools open, Chromium-based browsers also
# fetch the CDN assets' source maps - a connect-src fetch that would log a
# console CSP violation. Each relaxation below exists for one of those needs,
# and applies to /docs alone. Derived from the strict policy instead of
# hand-written, so every directive not named here can't drift apart
# (tests/test_security_headers.py enforces the exact delta).
DOCS_CSP = (
    SECURITY_HEADERS["Content-Security-Policy"]
    .replace(
        "script-src 'self'",
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    )
    .replace(
        "style-src 'self'",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    )
    .replace(
        "connect-src 'self'",
        "connect-src 'self' https://cdn.jsdelivr.net",
    )
    .replace("img-src 'self'", "img-src 'self' data: https://fastapi.tiangolo.com")
)


class SecurityHeadersMiddleware:
    """
    Pure ASGI wrapper stamping SECURITY_HEADERS on every HTTP response.

    When the docs are enabled, responses under /docs carry DOCS_CSP instead
    of the strict CSP; every other header is identical.

    Deliberately not @app.middleware("http") / add_middleware: Starlette puts
    user middleware *inside* its outermost ServerErrorMiddleware, so the 500
    it generates for an unhandled exception would skip user middleware and go
    out without these headers. Wrapping the finished app (see the `app`
    assignment at the bottom) keeps this outside the whole framework stack,
    so even those 500s are stamped.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap `app`, the downstream ASGI app receiving every request."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Normalized, not the raw path: browsers resolve dot segments before
        # sending, but raw clients need not, and StaticFiles serves the
        # *normalized* path - a raw /docs/../index.html is the homepage, which
        # must not be stamped with the relaxed docs CSP.
        path = posixpath.normpath(scope["path"])
        is_docs = DOCS_ENABLED and (path == "/docs" or path.startswith("/docs/"))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.update(SECURITY_HEADERS)
                if is_docs:
                    headers["Content-Security-Policy"] = DOCS_CSP
            await send(message)

        await self.app(scope, receive, send_with_headers)


MAX_SHOUT_LENGTH = 1000


class ShoutPayload(BaseModel):
    """Body of POST /api/shout - pydantic rejects anything without a string `text`."""

    text: str = Field(max_length=MAX_SHOUT_LENGTH)


class ShoutReply(BaseModel):
    """
    Reply of POST /api/shout - its own model, because replies aren't inputs.

    Reusing ShoutPayload would apply max_length to the *response*, and
    uppercasing can lengthen text ("ß".upper() == "SS") - valid input could
    then produce an invalid reply, a 500.
    """

    text: str


@fastapi_app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@fastapi_app.post("/api/shout")
async def shout(payload: ShoutPayload) -> ShoutReply:
    """Reply with the text uppercased - the frontend's example API round trip."""
    return ShoutReply(text=payload.text.upper())


@fastapi_app.exception_handler(StarletteHTTPException)
async def branded_404(request: Request, exc: StarletteHTTPException) -> Response:
    """
    Serve the branded 404 page for any 404 outside /api; else unchanged.

    StaticFiles raises HTTPException(404) for unknown paths, so this catches
    misses from the mount below as well as unmatched routes. /api keeps
    FastAPI's default JSON errors - browsers get a page, API clients get JSON.
    The 404 status is preserved: a "soft 404" (page with a 200) would make
    broken links look healthy to crawlers and monitoring.

    The page is deliberately NOT named 404.html: StaticFiles(html=True)
    special-cases that filename and would serve it for every miss itself -
    including /api/* misses, which must stay JSON and never reach this
    handler's check.
    """
    path = request.url.path
    if exc.status_code == 404 and path != "/api" and not path.startswith("/api/"):
        return FileResponse(STATIC_DIR / "not-found.html", status_code=404)
    return await http_exception_handler(request, exc)


# Mounted last so /api routes take precedence over static files.
fastapi_app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

# The ASGI app uvicorn serves (`app.main:app`): the FastAPI stack wrapped so
# security headers land on every response, framework-generated 500s included.
app = SecurityHeadersMiddleware(fastapi_app)
