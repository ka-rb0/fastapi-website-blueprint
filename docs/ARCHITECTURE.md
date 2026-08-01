# Architecture decisions

Why the application is put together the way it is. The code states _what_
it does; this file preserves the _why_ behind the decisions that are easy
to "simplify" away and hard to rediscover after the resulting regression.
Each section names the module that implements it.

## Composition root (`src/app/factory.py`)

`create_app(settings)` is the only place where configuration, routers,
templates, middleware and exception handlers meet. Everything holding
per-app state is either passed in (settings) or created fresh per call
(the template environment, the pages router - a closure over its
templates); the API router is a stateless module-level constant, which is
safe because `include_router` copies its routes into each app. Two
`create_app` calls therefore share no mutable state -
`tests/test_app_factory.py` proves two differently configured apps
coexist in one process.

`create_app` returns the concrete outermost wrapper
(`SecurityHeadersMiddleware`), not an opaque `ASGIApp`: the class is
public API, and the concrete type is what lets tests and embedding code
unwrap to the FastAPI instance (`framework_app` in `tests/helpers.py`)
instead of guessing at private attributes.

Importing `app.factory` (or any other module in the package) is
side-effect free: no environment reads, no logging configuration, no app
construction. The one exception is `app.main`, the uvicorn entry point,
which exists precisely to perform the impure step, `Settings.from_env()`,
at the executable boundary. Tests and embedding code should import
`create_app` and never `app.main`.

The wrapper order returned by `create_app` is deliberate and asserted by
`framework_app` in `tests/helpers.py`, the unwrap helper every
in-process test goes through:

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
log level, an unrecognized `WEBSITE_ENABLE_DOCS` value) refuses to boot
instead of producing a misbehaving server - e.g.
`WEBSITE_TRUSTED_HOSTS=""` used to start an app that rejected every
request with a 400, and `WEBSITE_ENABLE_DOCS=true` would silently mean
_off_; now both fail fast at startup.

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
- `Referrer-Policy: strict-origin-when-cross-origin` is the modern
  browser default, made explicit for older browsers whose default
  (`no-referrer-when-downgrade`) leaks full URLs cross-origin.
- `Permissions-Policy` opts out of camera, microphone and geolocation:
  the frontend uses none of them, and the opt-out means embedded content
  can't use them either.

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

## URL generation (`src/app/templates/`)

The templates emit two kinds of URL. Every URL is built with `url_for`,
never written literally, so route names and `root_path` stay the single
source of truth; what differs is whether the URL keeps the origin
`url_for` puts in front of it.

**Rendering URLs are root-relative** - assets, form actions, in-site
links, written `{{ url_for(...).path }}`. The browser resolves them
against the origin it actually used, so the app never has to know its
own public address:

```jinja
<link rel="stylesheet" href="{{ url_for('static', path='css/style.css').path }}" />
```

Keeping the origin here makes the page depend on the app reconstructing
it from the request, which behind a TLS-terminating proxy means
uvicorn's `X-Forwarded-Proto` handling - and uvicorn honors that header
only from peers listed in `--forwarded-allow-ips`, which defaults to
`127.0.0.1` and is therefore never the proxy in a container. A wrong
reconstruction emits every asset URL as `http://` on an `https://` page,
where the app's **own** CSP (`style-src 'self'`) blocks it as
cross-origin: the site renders unstyled, with a dead theme switch and a
dead shout form, because both ship `hidden` and are revealed by
JavaScript that never loads. Root-relative URLs remove the guess, so
that failure cannot occur however the deployment is wired.

**The canonical link is absolute** - one per indexable page, written
with a bare `url_for`:

```jinja
<link rel="canonical" href="{{ url_for('index') }}" />
```

A crawler needs the single address to index, and `/` is a different page
on every host that serves it, so this URL has to carry the scheme and
host. That makes it the one place the proxy-header configuration is
load-bearing: a deployment that does not set `--forwarded-allow-ips`
advertises an `http://` canonical for an HTTPS site. The failure is a
wrong hint to search engines rather than a broken page, which is why
this is the right - and only - URL to spend it on. The 404 page carries
no canonical link: it would tell crawlers a missing address is the
homepage.

Any further URL that leaves the page - an `og:url`, a sitemap, a link in
an e-mail - belongs in the absolute category for the same reason.

`tests/test_url_generation.py` pins both kinds and the prefix handling
of each; `tests/test_url_prefix.py` covers `root_path` across the whole
page. One sharp edge worth knowing: `URL.path` drops query strings and
fragments. `url_for` produces neither, but a helper that chains
`.include_query_params(...)` before `.path` would silently lose them.

## Trusted hosts (`src/app/factory.py`, `Settings.trusted_hosts`)

`url_for` builds URLs from the request's `Host` header, and the
homepage's canonical link (see above) puts one of them in front of
search engines - so an unlisted `Host` would advertise an
attacker-chosen address as this site's indexable one.
`TrustedHostMiddleware` rejects those requests before any template
renders, and `tests/test_trusted_hosts.py` asserts that the trusted host
is the only origin a rendered page names. Operational notes
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

The two rejection paths deliberately produce the same JSON error shape,
by different mechanisms. The pre-routing path sends a hand-rolled
`JSONResponse` (no framework has seen the request yet), so its
`{"detail": ...}` body mirrors FastAPI's error shape by convention -
`tests/test_api.py` asserts the parity. The streaming path raises
`HTTPException` from inside the app's own `receive()` call: the raise
surfaces inside the endpoint's body read, _within_ the framework's
exception handling, which is what lets a wrapper sitting outside the
framework stack produce a framework-shaped 413 (same JSON shape as a
422). Don't "simplify" the raise into a directly sent response - by the
time the stream exceeds the cap, the endpoint is mid-request and only
the framework knows whether a response has already started.

## Branded 404 (`src/app/exceptions.py`)

Registered on status code `404`, not on `StarletteHTTPException`, so
other HTTP errors (405, ...) never enter it - and status-code handlers
still catch raised exceptions, so it sees misses from the `StaticFiles`
mount as well as unmatched routes. `/api` paths fall through to
FastAPI's default JSON errors: browsers get a page, API clients get
JSON. The 404 status is preserved - a "soft 404" (branded page with a 200) would make broken links look healthy to crawlers and monitoring.

## Interactive docs gating (`src/app/factory.py`, `Settings.docs_enabled`)

The interactive API docs are a development tool: `/docs` only exists
when `WEBSITE_ENABLE_DOCS=1` (the devcontainer sets it; production
should not). The page needs the CSP exceptions above, so keeping it out
of production also keeps production on the strict policy everywhere.
`openapi.json` gates on the same flag - the machine-readable schema is a
dev tool just like the docs UI that consumes it - and ReDoc stays off:
one docs UI is enough, and each one is its own set of CSP exceptions.

## Static files (`src/app/factory.py`)

Mounted at `/` **last**, so real routes always take precedence, and
**without** `html=True`: its `index.html`/`404.html` special-casing
belonged to an all-static frontend, and misses must instead raise 404s
for the branded handler above.

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

The lifespan handler is created per app by `create_lifespan(settings)` -
a closure over its settings, like the pages router, so runtime code
never reads configuration back off `app.state` (state is an
introspection point for tests and embedding code only).

Logging is configured at startup, not import: importing the package
(tests, tooling) must not reconfigure the process-wide root logger.
Note that `logging.basicConfig` is still process-global and first-wins -
when several apps run in one process, the first lifespan to start
determines the root log level. That is an accepted limitation: per-app
isolation covers routing, templates and middleware, not process-wide
services.

### Bounded graceful shutdown (`.devcontainer/Dockerfile`)

Shutdown is only half the app's business: the lifespan handler runs after
uvicorn has stopped accepting connections and drained the ones still open,
and how long uvicorn is willing to wait for that is a server flag, not an
app setting. Its default is _no_ limit - one request that never finishes
(a slow client, a stuck upstream, an idle streaming response) keeps the
process alive indefinitely after SIGTERM. Under an orchestrator that
inverts the intent of a rolling deploy: the replica hangs until the
termination grace period expires, then SIGKILL severs every connection,
including the ones that were draining cleanly. So the distribution image
passes `--timeout-graceful-shutdown "${WEBSITE_GRACEFUL_SHUTDOWN_SECONDS}"`
(default 20s).

The value is load-bearing only in relation to the orchestrator's own
grace period - Kubernetes `terminationGracePeriodSeconds` (30s by
default), `docker stop --time` (10s by default). Keep it _below_ that
period, so the process decides when to give up and exits with its logs
flushed instead of being killed; raising it above the grace period
restores the original failure. Deployments whose requests legitimately
outlive 20s must raise both, in that order.

`tests/test_graceful_shutdown.py` pins the relationship in both
directions: that the image's command carries a finite timeout, and that
uvicorn actually abandons an in-flight request once it expires.

## Testing strategy (`tests/`)

API and security tests run against live uvicorn servers with plain
`urllib` - no httpx/TestClient dependency (see `tests/conftest.py`).
Configuration variants that used to need their own server process (docs
disabled) are now exercised in-process through `create_app` in
`tests/test_app_factory.py`; only variants that genuinely need server
behavior (`--root-path`, proxy headers, trusted hosts against real
sockets) keep dedicated server fixtures.

In-process tests build apps through `create_app` and unwrap them with
`framework_app` in `tests/helpers.py`; none import `app.main` - that
import constructs an app from the shell's environment, so a stray
variable would kill test collection instead of failing one test. The
entry point is still covered: the live-server fixtures run
`uvicorn app.main:app` in subprocesses, and subprocess coverage
(`patch = ["subprocess"]` in `pyproject.toml`) sees it.
