"""
FastAPI Website Blueprint server.

Serves the pages (Jinja2 templates from src/app/templates), the static
assets (src/app/static) and the /api endpoints.

Run with:  uvicorn app.main:app --host 0.0.0.0 --port $WEBSITE_INTERNAL_PORT --reload
"""

import logging
import os
import posixpath
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

# _utils is private (leading underscore, no compatibility promise) - but
# get_route_path is the exact function FastAPI's own router and StaticFiles
# use to strip root_path back off scope["path"] before matching a route.
# Relying on it, rather than reimplementing it, guarantees every
# root_path-aware check in this file always agrees with what the router
# actually served, even if Starlette's root_path handling itself changes -
# and if this import ever breaks, the app's own routing breaks on the same
# upgrade, loudly, so the risk is self-announcing. (starlette.routing also
# has this name in scope, but only via an implicit re-export with no __all__
# guarding it - this repo's mypy strict setting rejects relying on that.)
from starlette._utils import get_route_path
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"


def theme_css_pair(token: str) -> dict[str, str]:
    """
    Read a design token's (light, dark) hex pair from css/theme.css.

    The CSS file stays the single source of truth for the design tokens; the
    templates get the values injected (see the Jinja globals below) instead
    of mirroring them by hand.
    """
    css = (STATIC_DIR / "css" / "theme.css").read_text()
    hex_color = r"#[0-9a-fA-F]{6}"
    match = re.search(
        rf"--{token}:\s*light-dark\(({hex_color}),\s*({hex_color})\)", css
    )
    if match is None:
        raise RuntimeError(f"--{token}: light-dark(...) not found in css/theme.css")
    return {"light": match.group(1), "dark": match.group(2)}


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

# Host-header allowlist - Starlette's recommended guard against Host-header
# attacks. Every URL the templates emit comes from url_for, which builds
# absolute URLs from the request's Host header, so without this an arbitrary
# Host would be reflected into the rendered asset and form URLs. Harmless
# while nothing consumes those URLs downstream, dangerous the moment a cache,
# account e-mail, or absolute redirect is built on top of this blueprint -
# so the guard ships now, not then. The default trusts only local development
# names; a production deployment must set WEBSITE_TRUSTED_HOSTS to its public
# host name(s), comma-separated ("*.example.com" wildcards work). Keep
# 127.0.0.1 in any override: the distribution image's HEALTHCHECK and the
# test suite's readiness polls probe it. Requests from other hosts get a
# plain 400 - still stamped with the security headers, because the
# SecurityHeadersMiddleware wrapper at the bottom sits outside this.
TRUSTED_HOSTS = [
    host.strip()
    for host in os.environ.get("WEBSITE_TRUSTED_HOSTS", "localhost,127.0.0.1").split(
        ","
    )
    if host.strip()
]
fastapi_app.add_middleware(TrustedHostMiddleware, allowed_hosts=TRUSTED_HOSTS)

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

        # scope["path"] is root_path-relative, not app-relative: per the ASGI
        # spec (and uvicorn's own full_path = root_path + path), a reverse
        # proxy deployment with --root-path /prefix turns every request's
        # path into "/prefix/docs", not "/docs". get_route_path() undoes
        # exactly that - the same reversal FastAPI's own router applies
        # before matching /docs, so this check stays in sync with what the
        # router actually served. Without it, a proxied /docs request gets
        # the strict CSP (script-src 'self' etc.), and Swagger UI's
        # cdn.jsdelivr.net assets and inline bootstrap script get silently
        # CSP-blocked - a blank page.
        # Normalized, not the raw path: browsers resolve dot segments before
        # sending, but raw clients need not, and StaticFiles serves the
        # *normalized* path - a raw /docs/../css/theme.css is a real asset,
        # which must not be stamped with the relaxed docs CSP.
        path = posixpath.normpath(get_route_path(scope))
        # A prefix match, not /docs exactly: FastAPI serves more than one page
        # under it (/docs/oauth2-redirect boots with an inline script too).
        # Deliberately broader than a route-by-route list - a 404 *under*
        # /docs/... also carries the relaxed policy (harmless: the 404 page
        # reflects nothing, and the docs only exist in development) - because
        # a subtree match survives the framework adding docs routes, and it is
        # the pattern to copy when a new section needs its own CSP.
        is_docs = DOCS_ENABLED and (path == "/docs" or path.startswith("/docs/"))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.update(SECURITY_HEADERS)
                if is_docs:
                    headers["Content-Security-Policy"] = DOCS_CSP
            await send(message)

        await self.app(scope, receive, send_with_headers)


# One transport-level cap for every endpoint, not a per-field ceiling: field
# limits like MAX_SHOUT_LENGTH below only apply after FastAPI has received
# and JSON-decoded the entire body, so on their own a client could stream an
# arbitrarily large request into memory. 1 MB (10^6 bytes - the same count
# Caddy's "1MB" means in .devcontainer/Caddyfile, which mirrors this cap at
# the dev proxy) is far above any form on the site; raise it deliberately
# when an endpoint really needs more, e.g. file uploads.
MAX_BODY_BYTES = int(os.environ.get("WEBSITE_MAX_BODY_BYTES", "1000000"))


class BodySizeLimitMiddleware:
    """
    Pure ASGI guard: request bodies over MAX_BODY_BYTES get a 413.

    A reverse proxy should enforce the same cap in front (the development
    Caddyfile does), but this guard is what protects a directly exposed
    container - the distribution image runs uvicorn with no proxy of its own.

    Wraps `receive`, not `send`: a body with an oversized declared
    Content-Length fails on the app's first read without consuming a byte,
    and chunked or lying uploads are counted as they stream and cut off at
    the first byte past the limit. Raising HTTPException (rather than
    sending a response here) hands the 413 to the framework's exception
    handling, so API clients get the same JSON error shape as a 422. The
    raise happens inside the app's own receive() call, which is what makes
    that work even though this wrapper sits outside the framework stack.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int = MAX_BODY_BYTES) -> None:
        """Wrap `app`, the downstream ASGI app receiving every request."""
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # int() without try/except: uvicorn's HTTP parser has already
        # rejected requests whose Content-Length is not a valid integer.
        declared = Headers(scope=scope).get("content-length")
        too_large_by_declaration = (
            declared is not None and int(declared) > self.max_body_bytes
        )
        received = 0

        async def guarded_receive() -> Message:
            nonlocal received
            if too_large_by_declaration:
                raise StarletteHTTPException(
                    413, detail=f"Request body exceeds {self.max_body_bytes} bytes"
                )
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise StarletteHTTPException(
                        413, detail=f"Request body exceeds {self.max_body_bytes} bytes"
                    )
            return message

        await self.app(scope, guarded_receive, send)


MIN_SHOUT_LENGTH = 1
MAX_SHOUT_LENGTH = 1000

# The pages are server-rendered from these templates so shared values live in
# exactly one place: the base template holds the header/footer skeleton, and
# the globals below feed it what used to be hand-mirrored - design tokens from
# css/theme.css and the shout limits for the input's minlength/maxlength.
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["theme_color"] = theme_css_pair("bg")
templates.env.globals["min_shout_length"] = MIN_SHOUT_LENGTH
templates.env.globals["max_shout_length"] = MAX_SHOUT_LENGTH


class ShoutPayload(BaseModel):
    """Body of POST /api/shout - pydantic rejects anything but a non-empty string `text`."""

    text: str = Field(min_length=MIN_SHOUT_LENGTH, max_length=MAX_SHOUT_LENGTH)


class ShoutReply(BaseModel):
    """
    Reply of POST /api/shout - its own model, because replies aren't inputs.

    Reusing ShoutPayload would apply max_length to the *response*, and
    uppercasing can lengthen text ("ß".upper() == "SS") - valid input could
    then produce an invalid reply, a 500.
    """

    text: str


# Not in the OpenAPI schema: /docs documents the JSON API, not the pages.
@fastapi_app.head("/", include_in_schema=False)
@fastapi_app.get("/", include_in_schema=False)
async def index(request: Request) -> Response:
    """Render the homepage."""
    return templates.TemplateResponse(request, "index.html")


@fastapi_app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@fastapi_app.post("/api/shout")
async def shout(payload: ShoutPayload) -> ShoutReply:
    """Reply with the text uppercased - the frontend's example API round trip."""
    return ShoutReply(text=payload.text.upper())


@fastapi_app.exception_handler(404)
async def branded_404(request: Request, exc: StarletteHTTPException) -> Response:
    """
    Render the branded 404 page for any 404 outside /api; /api stays JSON.

    Registered on the status code rather than StarletteHTTPException, so
    other HTTP errors (405, ...) never enter it. Status-code handlers still
    catch raised HTTPExceptions, so this sees misses from the StaticFiles
    mount below as well as unmatched routes. /api falls through to FastAPI's
    default JSON errors - browsers get a page, API clients get JSON.
    The 404 status is preserved: a "soft 404" (page with a 200) would make
    broken links look healthy to crawlers and monitoring.

    get_route_path(request.scope), not request.url.path: URL.path is built
    straight from scope["path"] with no root_path stripped off (see
    starlette.datastructures.URL.__init__), so behind a reverse proxy's
    --root-path it would be "/prefix/api/..." - failing this check and
    handing API clients an HTML error body instead of JSON.
    """
    path = get_route_path(request.scope)
    if path != "/api" and not path.startswith("/api/"):
        return templates.TemplateResponse(request, "not-found.html", status_code=404)
    return await http_exception_handler(request, exc)


# Assets only (css/, js/, favicon.svg) - the pages are routes above. Mounted
# last so real routes take precedence. No html=True: its index.html/404.html
# special-casing belonged to the all-static frontend; misses now raise 404s
# that the handler above turns into the branded page.
fastapi_app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")

# The ASGI app uvicorn serves (`app.main:app`): the FastAPI stack wrapped so
# security headers land on every response, framework-generated 500s included,
# and no request can stream more than MAX_BODY_BYTES into memory. Headers
# outermost: the body guard never sends a response itself, but keeping the
# header stamp on the outside is what guarantees it covers everything.
app = SecurityHeadersMiddleware(BodySizeLimitMiddleware(fastapi_app))
