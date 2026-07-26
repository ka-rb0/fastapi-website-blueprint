# Architecture decisions

Why the application is put together the way it is. The code states _what_
it does; this file preserves the _why_ behind the decisions that are easy
to "simplify" away and hard to rediscover after the resulting regression.
Each section names the module that implements it.

## Composition root (`src/app/factory.py`)

`create_app(settings)` is the only place where configuration, routers,
templates, middleware and exception handlers meet. Everything it composes
is either passed in (settings) or created fresh per call (template
environment, routers with closures), so two `create_app` calls share no
mutable state - `tests/test_app_factory.py` proves two differently
configured apps coexist in one process.

Importing `app.factory` (or any other module in the package) is
side-effect free: no environment reads, no logging configuration, no app
construction. The one exception is `app.main`, the uvicorn entry point,
which exists precisely to perform the impure step, `Settings.from_env()`,
at the executable boundary. Tests and embedding code should import
`create_app` and never `app.main`.

The wrapper order returned by `create_app` is deliberate and asserted by
`tests/test_security_headers.py`:

```text
SecurityHeadersMiddleware        <- outermost: stamps every response
  BodySizeLimitMiddleware        <- its 413s must carry the headers
    FastAPI (ServerErrorMiddleware, TrustedHostMiddleware, routers, ...)
```

Both wrappers are pure ASGI classes, _not_ `add_middleware`, because
Starlette places user middleware inside its outermost
`ServerErrorMiddleware`: a 500 generated for an unhandled exception would
skip `add_middleware`-registered middleware and leave without security
headers. Wrapping the finished app keeps even those 500s stamped.

## Settings (`src/app/config.py`)

A frozen, slotted dataclass validated in `__post_init__`: an instance
that exists is safe to build an app from. Invalid configuration
(no trusted hosts after stripping blanks, non-positive body cap, unknown
log level) refuses to boot instead of producing a misbehaving server -
e.g. `WEBSITE_TRUSTED_HOSTS=""` used to start an app that rejected every
request with a 400; now it fails fast at startup.

`Settings.from_env()` accepts an explicit mapping so tests can exercise
parsing without touching `os.environ`. Defaults are production-safe:
docs off, localhost-only hosts, 1 MB body cap.

## Security headers and CSP (`src/app/middleware.py`)

`SECURITY_HEADERS` goes on **every** response - static files, API,
errors. Highlights of the individual choices:

- The CSP allows only same-origin resources, matching the self-contained
  frontend (no CDNs, no inline scripts - even the pre-paint theme script
  is a file, `js/theme-init.js`, for exactly this reason). Extend the CSP
  when you add external resources; don't drop it.
- No `Strict-Transport-Security` on purpose: HSTS belongs at the
  TLS-terminating reverse proxy - the app only ever speaks plain HTTP.
- `X-Frame-Options` is the legacy complement of the CSP's
  `frame-ancestors` for pre-CSP2 browsers; the `Cross-Origin-*` headers
  deny window handles and cross-origin embedding (tab-nabbing, XS-Leaks,
  Spectre-class side channels) before the app ever has authenticated
  pages to protect.

### The docs CSP exception

`DOCS_CSP` is **derived** from the strict policy with `.replace()`, never
hand-written, so any directive not explicitly relaxed cannot drift -
`tests/test_security_headers.py` enforces the exact delta. Each of the
four relaxations exists for a concrete need of FastAPI's generated
Swagger UI page:

- `script-src` / `style-src` + `'unsafe-inline'` + `cdn.jsdelivr.net`:
  the page loads Swagger UI from the CDN, boots it with an inline script,
  and the UI injects inline styles while rendering.
- `img-src` + `data:` + `fastapi.tiangolo.com`: the UI draws `data:`
  images; the favicon comes from FastAPI's site.
- `connect-src` + `cdn.jsdelivr.net`: with dev tools open,
  Chromium-based browsers fetch the CDN assets' source maps.

The relaxed policy applies to the `/docs` subtree by **prefix match**,
not a route list: FastAPI serves more than one page under it
(`/docs/oauth2-redirect` boots with an inline script too), and a subtree
match survives the framework adding docs routes. A 404 _under_ `/docs/`
also carries the relaxed policy - harmless, the 404 page reflects
nothing and the docs only exist in development. This is the pattern to
copy when a page of yours needs its own CSP exception.

The path is normalized (`posixpath.normpath`) after `root_path` removal
before the prefix check: browsers resolve dot segments before sending,
but raw clients need not, and `StaticFiles` serves the _normalized_
path - a raw `/docs/../css/theme.css` is a real asset and must get the
strict CSP, not the docs relaxation.

## `root_path` handling (`src/app/middleware.py`, `src/app/exceptions.py`)

Never compare `scope["path"]` or `request.url.path` against a route
string. Behind a reverse proxy (`uvicorn --root-path /prefix`) every
request path arrives as `/prefix/docs`, so bare comparisons silently
break under path-prefixed deployments while working fine unprefixed -
this bit both the CSP middleware and the branded-404 handler once.
Always use `get_route_path(scope)`, the same reversal FastAPI's router
applies before matching. It is imported from `starlette._utils` (the
defining module) rather than `starlette.routing`'s implicit re-export:
the private import is the exact function the router and `StaticFiles`
use, so these checks can never disagree with what was actually served,
and mypy strict rejects the un-`__all__`-ed re-export anyway. If the
import ever breaks on an upgrade, the app's own routing breaks loudly on
the same upgrade - the risk is self-announcing.

## Trusted hosts (`src/app/factory.py`, `Settings.trusted_hosts`)

Every URL the templates emit comes from `url_for`, which builds absolute
URLs from the request's `Host` header - without an allowlist, an
arbitrary `Host` would be reflected into rendered asset and form URLs.
Harmless while nothing consumes those URLs downstream, dangerous the
moment a cache, account e-mail, or absolute redirect is built on top of
this blueprint - so the guard ships now, not then. Operational notes
(the allowlist matches site names, wildcards, keeping `127.0.0.1` for
the container healthcheck) live in [QUICKSTART.md](QUICKSTART.md).
Rejected requests get a plain 400 that still carries the security
headers, because `SecurityHeadersMiddleware` sits outside the framework.

## Request body cap (`src/app/middleware.py`, `Settings.max_body_bytes`)

One transport-level cap for every endpoint, not per-field ceilings:
field limits like `MAX_SHOUT_LENGTH` only apply after FastAPI has
received and JSON-decoded the entire body, so on their own a client
could stream an arbitrarily large request into memory. The default,
10^6 bytes, is the same count Caddy's `1MB` means in
`.devcontainer/Caddyfile`, which mirrors the cap at the dev proxy.

An oversized declared `Content-Length` is rejected before routing
(`int()` without try/except - uvicorn's parser already rejected
non-integer values), so the cap also covers endpoints and error paths
that never read the body. Chunked or lying uploads are counted as the
app consumes them and cut off at the first byte past the limit. A
proxy-level cap is still required to reject an oversized chunked body
when the selected route never consumes it; the in-app guard is what
protects a directly exposed container - the distribution image runs
uvicorn with no proxy of its own.

## Branded 404 (`src/app/exceptions.py`)

Registered on status code `404`, not on `StarletteHTTPException`, so
other HTTP errors (405, ...) never enter it - and status-code handlers
still catch raised exceptions, so it sees misses from the `StaticFiles`
mount as well as unmatched routes. `/api` paths fall through to
FastAPI's default JSON errors: browsers get a page, API clients get
JSON. The 404 status is preserved - a "soft 404" (branded page with a 200) would make broken links look healthy to crawlers and monitoring.

## Static files (`src/app/factory.py`)

Mounted at `/` **last**, so real routes always take precedence, and
**without** `html=True`: its `index.html`/`404.html` special-casing
belonged to an all-static frontend, and misses must instead raise 404s
for the branded handler above. The docs UI is gated together with
`openapi.json` (the schema is a dev tool just like the UI consuming it),
and ReDoc stays off - each docs UI is its own set of CSP exceptions.

## Schemas (`src/app/schemas.py`)

`ShoutReply` is a separate model from `ShoutPayload` because replies
aren't inputs: reusing the payload model would apply `max_length` to the
_response_, and uppercasing can lengthen text (`"ß".upper() == "SS"`) -
valid input could then produce an invalid reply, a 500.

## Templating (`src/app/templating.py`)

`css/theme.css` is the single source of truth for design tokens;
`theme_css_pair` parses the values out and injects them (with the shout
length limits) as Jinja globals, so templates never mirror values by
hand. `tests/test_static_consistency.py` guards the pipeline. Each app
instance gets its own `Jinja2Templates` environment from
`create_templates()` so template globals can never leak between
differently configured apps.

## Lifecycle (`src/app/lifecycle.py`)

Logging is configured at startup, not import: importing the package
(tests, tooling) must not reconfigure the process-wide root logger.
Note that `logging.basicConfig` is still process-global and first-wins -
when several apps run in one process, the first lifespan to start
determines the root log level. That is an accepted limitation: per-app
isolation covers routing, templates and middleware, not process-wide
services.

## Testing strategy (`tests/`)

API and security tests run against live uvicorn servers with plain
`urllib` - no httpx/TestClient dependency (see `tests/conftest.py`).
Configuration variants that used to need their own server process (docs
disabled) are now exercised in-process through `create_app` in
`tests/test_app_factory.py`; only variants that genuinely need server
behavior (`--root-path`, proxy headers, trusted hosts against real
sockets) keep dedicated server fixtures.
