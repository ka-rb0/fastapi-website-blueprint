"""
FastAPI Website Blueprint server.

Serves the static frontend from src/app/static and the /api endpoints.

Run with:  uvicorn app.main:app --host 0.0.0.0 --port $WEBSITE_INTERNAL_PORT --reload
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.datastructures import MutableHeaders
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


fastapi_app = FastAPI(title="FastAPI Website Blueprint", lifespan=lifespan)

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
    "Referrer-Policy": "same-origin",
    # No cross-window handles on this site from cross-origin openers, and no
    # cross-origin embedding of this site's resources.
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    # The frontend uses none of these; opt out so embedded content can't either.
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class SecurityHeadersMiddleware:
    """
    Pure ASGI wrapper stamping SECURITY_HEADERS on every HTTP response.

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

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).update(SECURITY_HEADERS)
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


# Mounted last so /api routes take precedence over static files.
fastapi_app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

# The ASGI app uvicorn serves (`app.main:app`): the FastAPI stack wrapped so
# security headers land on every response, framework-generated 500s included.
app = SecurityHeadersMiddleware(fastapi_app)
