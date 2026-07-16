"""
FastAPI Website Blueprint server.

Serves the static frontend from src/app/static and the /api endpoints.

Run with:  uvicorn app.main:app --host 0.0.0.0 --port $WEBSITE_INTERNAL_PORT --reload
"""

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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


app = FastAPI(title="FastAPI Website Blueprint", lifespan=lifespan)

# Defense-in-depth headers on every response (static files and API alike).
# The CSP allows only same-origin resources, which matches the self-contained
# frontend (no CDNs, no inline scripts - even the pre-paint theme script is a
# file, js/theme-init.js, for exactly this reason). Extend the CSP when you
# add external resources; don't drop it.
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
    "Referrer-Policy": "same-origin",
}


@app.middleware("http")
async def add_security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/shout")
def shout(payload: ShoutPayload) -> ShoutReply:
    """Reply with the text uppercased - the frontend's example API round trip."""
    return ShoutReply(text=payload.text.upper())


# Mounted last so /api routes take precedence over static files.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
