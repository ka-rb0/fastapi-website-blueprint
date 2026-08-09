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
(`RequestIDMiddleware`), not an opaque `ASGIApp`: the classes are
public API, and the concrete types are what let tests and embedding code
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
RequestIDMiddleware              <- outermost: nothing below it logs or
  SecurityHeadersMiddleware         answers without a correlation ID
    BodySizeLimitMiddleware      <- its 413s must carry both
      FastAPI (OpenTelemetry, ServerErrorMiddleware, TrustedHostMiddleware, ...)
```

The OpenTelemetry server span is the outermost thing _inside_ FastAPI
when telemetry is enabled, and nothing when it is not - see "Telemetry"
for why it belongs there rather than beside the wrappers above.

All three wrappers are pure ASGI classes, _not_ `add_middleware`, because
Starlette places user middleware inside its outermost
`ServerErrorMiddleware`: a 500 generated for an unhandled exception would
skip `add_middleware`-registered middleware and leave without security
headers - or, for the same reason, without an ID to find it by. Wrapping
the finished app keeps even those 500s stamped and correlated.

## Settings (`src/app/config.py`)

A frozen, slotted dataclass validated in `__post_init__`: an instance
that exists is safe to build an app from. Invalid configuration
(no trusted hosts after stripping blanks, a malformed host pattern,
non-positive body cap, unknown log level or log format, an unrecognized
`WEBSITE_ENABLE_DOCS` value)
refuses to boot instead of producing a misbehaving server - e.g.
`WEBSITE_TRUSTED_HOSTS=""` used to start an app that rejected every
request with a 400, and `WEBSITE_ENABLE_DOCS=true` would silently mean
_off_; now both fail fast at startup. `log_format` is typed as the
`LogFormat` enum instead, so the only place it can be wrong is on the way
in from the environment, and `from_env` is where that is caught.

`Settings.from_env()` accepts an explicit mapping so tests can exercise
parsing without touching `os.environ`. Defaults are production-safe:
docs off, localhost-only hosts, 1 MB body cap, human-readable logs (the
image opts into JSON, see "Distribution image"), telemetry off until a
collector is named (see "Telemetry").

The `OTEL_*` variables are the one group read by somebody else's rules
rather than this module's - `Settings` decides only _whether_ telemetry
happens, and everything about how it happens stays with the SDK that
already specifies it.

Trusted-host entries are lowercased and validated against Starlette's host
pattern contract before the application exists: an exact ASCII host name,
`*.example.com`, or the explicit `"*"` opt-out. Schemes, ports, paths,
whitespace, IPv6 literals (unsupported by Starlette's current matcher) and
malformed wildcards fail with a configuration error instead of surfacing as a
late framework assertion or an allowlist that can never match. Incoming host
names are lowercased before matching too; their optional request port remains
available to redirects and URL generation.

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
  `frame-ancestors` for pre-CSP2 browsers; by default, the `Cross-Origin-*`
  headers deny window handles and cross-origin embedding (tab-nabbing,
  XS-Leaks, Spectre-class side channels) before the app ever has
  authenticated pages to protect. The docs' OAuth-specific exception is
  described below.
- `Referrer-Policy: strict-origin-when-cross-origin` is the modern
  browser default, made explicit for older browsers whose default
  (`no-referrer-when-downgrade`) leaks full URLs cross-origin.
- `Permissions-Policy` opts out of camera, microphone and geolocation:
  the frontend uses none of them, and the opt-out means embedded content
  can't use them either.

### The docs browser-policy exceptions

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
before the prefix check, so the relaxation follows where a request
resolves rather than how a client spelled it: browsers resolve dot
segments before sending, but raw clients need not, so a literal
`/docs/../static/css/theme.css` arrives with its `/docs` prefix intact
while pointing outside the subtree, and would otherwise carry the docs
policies out of it.

The docs subtree also changes `Cross-Origin-Opener-Policy` from the
site-wide `same-origin` to `same-origin-allow-popups`. Swagger UI's OAuth
flow opens the identity provider on another origin, then returns to
`/docs/oauth2-redirect`, whose script reads `window.opener` to deliver the
authorization result. `same-origin` severs that relationship when the popup
crosses origins; `same-origin-allow-popups` is the narrow policy intended for
OAuth integrations. The same normalized subtree check scopes both exceptions,
and tests assert that neither can leak through dot segments or `root_path`.

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
Uvicorn's `X-Forwarded-Proto` handling - and Uvicorn honors that header
only from peers listed in `UVICORN_FORWARDED_ALLOW_IPS`, which defaults to
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
load-bearing: a deployment that does not set `UVICORN_FORWARDED_ALLOW_IPS`
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
is the only origin a rendered page names. Operational notes (the
allowlist matches site names, wildcards) live in
[QUICKSTART.md](QUICKSTART.md). Rejected requests get a plain 400 that
still carries the security headers, because `SecurityHeadersMiddleware`
sits outside the framework.

`HostValidationMiddleware` (`src/app/middleware.py`) is what applies that
check, and it exempts exactly the probe routes below (`PROBE_PATHS`). A
Kubernetes `httpGet` probe addresses the pod by the IP it was scheduled
with and sends it as `Host`, so no allowlist can contain it - a guarded
probe route means every pod fails its own liveness check and restarts
forever, on a deployment that is otherwise configured correctly. Those
routes can be exempt because the invariant above does not reach them:
they render no template and reflect nothing of the request, they answer a
constant `{"status": "ok"}`. That property is the price of admission to
`PROBE_PATHS` - `tests/test_trusted_hosts.py` parametrizes over the whole
tuple so a route added without it fails there. Nothing else is exempt,
and the comparison is deliberately exact (after `root_path` is removed,
never normalized) - normalizing would _widen_ an exemption, the opposite
of the CSP check, where it narrows a relaxation. `/livez/` is the case
that shows it: the router answers the trailing-slash form with a redirect
whose `Location` it builds from the `Host` header.

## Probe endpoints (`src/app/routers/probes.py`)

Three paths, two decisions:

| Path       | Failure means              | Orchestrator's response   |
| ---------- | -------------------------- | ------------------------- |
| `/livez`   | the process is wedged      | restart the container     |
| `/readyz`  | this instance can't serve  | stop routing to it        |
| `/healthz` | legacy alias for the above | (whatever it is wired to) |

The split is the point, not the spelling. Nothing reads the path - a
probe's URL is configuration (`httpGet.path`), and the `z` suffix is a
Google-ism Kubernetes inherited - so what the names buy is a place for
the two decisions to live separately. **Dependency checks belong in
`readyz` and never in `livez`**: liveness failing is answered by killing
the container, so a liveness check that reaches a database converts one
slow dependency into every replica restarting at once, which cannot
repair a dependency and destroys the capacity that was still serving.
Readiness failing is answered by removing the instance from rotation
while it keeps running and recovers, which is the response that fits.

`/healthz` is kept for tooling that reaches for the name unprompted, and
is documented as an alias rather than a third opinion - Kubernetes
deprecated it on its own API server in v1.16 and replaced it with the
other two, for the reason above. If it ever has to stop being a constant
it should follow readiness; the wrong guess there restarts the fleet.

This app depends on nothing, so all three currently answer the same
constant. That is the honest state of a blueprint, and the seam is what
has value: the check a fork eventually adds lands on the route wired to
the action that suits it, instead of on a single `health` route wired to
both.

**There is deliberately no readiness state that flips on shutdown.** The
obvious next step - fail `readyz` once SIGTERM arrives, so the load
balancer drains the instance before it stops - is already handled a layer
down, because uvicorn closes the listening socket immediately on SIGTERM
and only then drains in-flight requests. Measured against this app: a new
connection is refused 200 ms after the signal, while a request already in
flight keeps going (see "Bounded graceful shutdown" below).

```text
t+0.2s: connect -> [Errno 111] Connection refused
```

A probe gets a connection error, which every orchestrator already reads
as a failed probe, so a readiness flag would be machinery no probe could
ever observe. What the drain window actually needs is the orchestrator
removing the endpoint before it signals - a `preStop` hook - which is
deployment configuration, not something an endpoint can express.

The routes sit at the root rather than under `/api`: they answer an
operator, not a caller of the product's API, an ingress may want to route
or refuse them separately, and they must keep answering when every `/api`
route is gone. They return `ProbeStatus` rather than `dict[str, str]` so
the generated schema names the field - orchestrators decide on the status
code alone, but the body is documented surface.

The alternative was to make every deployment configure
`httpHeaders: [{name: Host, ...}]` on both probes, or list the pod CIDR
in `WEBSITE_TRUSTED_HOSTS` - a template should not hand its users a
rediscovery exercise, and the second answer weakens the allowlist that is
the point of this section.

## Request body cap (`src/app/middleware.py`, `Settings.max_body_bytes`)

One transport-level cap for every endpoint, not per-field ceilings:
field limits like `MAX_SHOUT_LENGTH` only apply after FastAPI has
received and JSON-decoded the entire body, so on their own a client
could stream an arbitrarily large request into memory. The default,
10^6 bytes, is the same count Caddy's `1MB` means in
`.devcontainer/Caddyfile`, which mirrors the cap at the dev proxy.

An oversized declared `Content-Length` is rejected before routing, so
the cap also covers endpoints and error paths that never read the body.
Chunked or lying uploads are counted as the app consumes them and cut
off at the first byte past the limit.

The declaration is read against RFC 9110's `1*DIGIT` rather than handed
to `int()`, which also accepts `+1`, `1` and `1_000` (silently 1000) -
forms no HTTP parser produces and none that should be read as a size.
Anything that does not match is treated as _no_ declaration rather than
as an error: HTTP framing is the server's job - uvicorn answers such a
request with a 400 before this app is ever called - while the cap is
this wrapper's, and the streaming counter enforces it on whatever bytes
arrive regardless. Raising instead would put a `ValueError` through the
whole stack of an embedding host whose parser is laxer than uvicorn's,
and it would escape _outside_ `ServerErrorMiddleware` (which sits inside
this wrapper), so the client would get no response at all rather than a 500. A
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

## Request correlation (`src/app/observability.py`, `src/app/middleware.py`)

Every request gets an ID. `RequestIDMiddleware` binds it to a
`ContextVar` for the duration of the request, echoes it on the response
as `X-Request-ID`, and `configure_logging` puts a `%(request_id)s` field
on every log record - so "it broke at 14:32" becomes one grep, and the
reporter can read the ID straight off the response without log access.

A context variable rather than something hung on the request, because
the code that logs is usually the code that never sees a request object:
a helper three calls down, a library logger. On a clean exit it is reset
on the way out of the middleware - each ASGI request already runs in its
own context, but that is the server's guarantee, not this app's, and an
app embedded in someone else's task must not leak an ID into whatever
runs next.

**When an exception is unwinding, the binding is deliberately kept.**
Uvicorn catches an unhandled exception _above_ this middleware and only
then logs the traceback ("Exception in ASGI application") - the one
record an operator most wants to find by ID, and the reason resetting in
a `finally` would be wrong: the reset would run mid-unwind, before
uvicorn logs, and file the traceback under `-`. The retained binding
dies with the request's context under any conforming ASGI server, which
runs each request in a context of its own. A host that instead catches
the exception in a task it keeps is left holding the stale ID: whatever
it logs in that context afterwards carries it, and because
`ContextVar.reset` restores the _previous_ value, the next clean request
through the middleware restores the stale ID rather than `-`. That is
the deliberate price of correlating the traceback - within one context
the two are mutually exclusive - and such a host recovers the guarantee
the moment it does what servers do: run each request in its own context
copy. `tests/test_request_id.py` pins both halves: reset after a clean
response, kept where the server's error logger runs.

A task spawned while a request is in flight inherits the request's ID -
`asyncio.create_task` copies the context - and keeps it after the
response completes, the parent's reset notwithstanding. Deliberate:
background work caused by a request belongs to that request's trace,
and the copied context is how the ID follows the work the same way it
follows a call stack. A detached job that deserves a trace of its own
rebinds with `bind_request_id(None)`, which always mints.

Only `http` scopes are correlated. A WebSocket connection passes through
the middleware untouched, so adding WebSocket routes means extending it -
and deciding what one ID should span for a long-lived connection.

Outermost in the stack (see "Composition root"), so responses produced
without an endpoint ever running - a body-cap 413, a rejected `Host`, an
unhandled exception's 500 - are findable by the same ID the client got
back. Those are the responses somebody actually goes looking for.

**Inbound IDs are kept, after a shape check.** A gateway or upstream
service that already picked an ID gets one trace across the whole call
chain instead of two unlinkable ones, which is the entire point of the
header. The check is the shape and nothing else - 1 to 64 visible ASCII
characters - because a correlation ID is an opaque token this app never
interprets; 64 admits a UUID, a 32-character hex string or a W3C
`traceparent`. Excluding space, the control characters and everything
non-ASCII is what makes echoing a client-supplied value safe: it can
neither split the response header nor forge a line in the log. Uvicorn's
parser already refuses most of those requests outright, so the guard is
the backstop for laxer hops - `tests/test_request_id.py` therefore tests
it directly rather than over the wire. Anything unusable is _replaced_,
never rejected: correlation is a diagnostic, and failing a request over
a cosmetic header would turn an upstream's bug into an outage.

The tradeoff of accepting the header is that a client can choose its own
ID and so name a trace after someone else's. That buys confusion in a
forensic search, nothing more - an ID authenticates nothing and grants
nothing - and the usual answer is to have the edge proxy overwrite the
header. A deployment that would rather not trust callers at all can drop
the `candidate` argument in `bind_request_id` and always mint.

**Uvicorn's loggers are adopted, not just the root logger.** Uvicorn
installs handlers on `uvicorn`/`uvicorn.access` and turns propagation
off, so its access line - the one line per request that says _which_
request - would be the one line without the ID. `configure_logging`
empties those handler lists and turns propagation back on, leaving the
process with a single handler on stdout: one formatter, so the ID is
everywhere, and one stream, so app and access lines cannot interleave
out of order the way two buffered ones do. Their levels become `NOTSET`
so they inherit the root level, which makes `LOG_LEVEL` mean what it
says instead of losing to uvicorn's hardcoded INFO. That one knob cuts
both ways: access lines are INFO, so `LOG_LEVEL=WARNING` quiets the
per-request line along with the app - deliberate, but worth knowing
before turning the level down in an incident.

That happens when `app.main` is imported - the executable boundary, not
`create_app` or the lifespan. Logging is deployment policy, and an
embeddable app that reconfigured the process from library code would
reach into every host that mounts it: its pytest capture, its JSON
pipeline, its `--log-config`. A host that never imports `app.main`
keeps its logging untouched and opts in by calling `configure_logging`
itself (exported from the package root for exactly that). The ordering
needs no flag to remember, because uvicorn configures its own logging
when its `Config` is constructed and imports the application module
afterwards - so the import wins. It wins under `--reload` and
`--workers` as well, where each child process re-runs uvicorn's setup
before loading the app.

Winning that race is the point, and it is also the sharp edge: importing
`app.main` silently **overrides the root and Uvicorn portions of
`uvicorn --log-config`**. An operator who points that flag at a JSON
pipeline for those loggers gets this module's human-readable format
instead, with nothing in the log to say that configuration was replaced.
Explicitly named non-Uvicorn loggers may retain handlers from the flag,
however, because this module leaves existing loggers enabled; the result
can therefore be mixed rather than a complete override. That is the
standing cost of claiming logging from the application module, and it is
the arrangement most likely to be hit, because `--log-config` is
uvicorn's documented way to reshape logs for a deployment. A deployment
that needs the flag honored should serve an entry point of its own that
calls `create_app` and never imports `app.main`.

The second arrangement that degrades does so in the other direction:
handing an already-imported app object to `uvicorn.run()` lets uvicorn's
later setup reclaim its own loggers, and the access line loses the ID.
The documented string entry point, `uvicorn app.main:app`, avoids that
second problem but retains the `--log-config` tradeoff above.

**The rendering is a setting, the schema is code.** `LOG_FORMAT` picks
`text` (the code default: what a developer tails locally, and a blueprint
should not presume a log pipeline) or `json` (one object per line, which
is what the distribution image's environment selects - see "Distribution
image" below). Picking is all it does: both renderings carry the same
fields, the correlation ID included, because `CorrelationFilter` puts it on
the record before either formatter sees it.

Splitting it that way is deliberate. Every deployment with an aggregator
in front of it wants JSON, so leaving that as an edit to a module
constant meant every project derived from this template making the same
edit, in its own way, in a template-owned file - the merge conflict on
the next template update that a standard template exists to avoid. What
stays in code is the field set: `TEXT_LOG_FORMAT` and `JSON_LOG_FIELDS`
in `src/app/observability.py` are this app's log schema, the thing a
dashboard and an alert are written against, and a schema belongs in
version control rather than in a container's environment. They are also
the wrong shape for an environment variable - a `%`-format string is code
that fails at log time instead of at boot, and the JSON field set is a
mapping with no sane flat encoding. Rename the JSON keys to a house
convention (ECS's `log.level`, Google Cloud's `severity`) by editing that
one mapping.

`JSON_LOG_FIELDS` is an allowlist rather than "every attribute of the
record": the keys are a contract with whatever parses the lines, so
widening the schema is a deliberate edit there and no `extra=` at a call
site can rename or add a field from a distance. `exc_info` and
`stack_info` are appended outside it, since both are absent from most
records and only `logging.Formatter` knows how to render them - dropping
them would ship uvicorn's "Exception in ASGI application" with the cause
gone, which is the one record the correlation ID exists for. Timestamps
are RFC 3339 in UTC, so records from replicas in different zones order
against each other.

`trace_id` and `span_id` are the two keys that behave differently: they
are _absent_ from a record rather than empty on it, because only a record
emitted while a span is current has a trace to name. They are what joins
a log line to the trace beside it (see "Telemetry" below), and they do
not replace the request ID - that one is on every record, including the
ones no trace covers (startup, shutdown, a request on a path telemetry
excludes, anything at all with no collector configured), and it is the
only one of the three the client is handed back. Uvicorn's access line -
the one line per request - carries all three, because uvicorn writes it
from the `send()` call the instrumentation is still wrapping;
`tests/test_telemetry.py` pins that the ID on that line is the trace the
collector received. The text rendering deliberately carries neither trace
field: it is what a developer tails in a terminal, where 48 hex
characters would be the part nobody reads.

`CorrelationFilter` reads the trace context through `opentelemetry-api`,
never the SDK. With no provider installed - the state of every deployment
that configured no collector - the API returns its documented no-op
objects, which is what lets that module import OpenTelemetry
unconditionally, with no feature flag and no `try: import`.

## Telemetry (`src/app/telemetry.py`)

Logs answer _what happened_. They cannot answer _how long the checkout
endpoint takes at p99_ without something aggregating them first, and
every alert worth having is a threshold on a number. So the app emits
OpenTelemetry traces and metrics as well - and emits them under the
names OpenTelemetry specifies, because that is the entire value on
offer: a fleet where `http.server.request.duration` means the same thing
on every service can share one dashboard and one alert, and a fleet where
each project invented a counter cannot.

Nothing here is written by hand. `opentelemetry-instrumentation-fastapi`
produces the server span and the HTTP metrics; the SDK reads endpoint,
headers, timeouts, compression, sampler, batch sizes and export intervals
from the standard `OTEL_*` variables. What this module owns is four
decisions the environment cannot express.

**Whether telemetry happens at all.** It is on exactly when a collector
endpoint is configured - `OTEL_EXPORTER_OTLP_ENDPOINT`, or either
per-signal variant, for a deployment that splits traces from metrics -
and off otherwise, which is the default and the whole of the off switch.
There is deliberately no `WEBSITE_ENABLE_TELEMETRY` beside it: an
endpoint variable _and_ a flag are two ways to say one thing, and the
deployment that sets one without the other is silently wrong either way.
Off means _absent_, not idle: no provider is installed, and `create_app`
adds no instrumentation, so a default deployment pays nothing rather
than paying to build spans that are dropped. `OTEL_SDK_DISABLED` is
honored as the specification's own kill switch - and by the
specification's rules, where only `"true"` is true and everything else is
false, unlike the strict `WEBSITE_ENABLE_DOCS`. The `OTEL_*` names belong
to OpenTelemetry; reading them the house way would make this the one
service in a fleet that refuses to start.

**That a misconfiguration fails at boot.** Exporting as
`unknown_service` is not a degraded state somebody notices later: the
data lands in the backend under a name shared with every other service
nobody named, where it cannot be dashboarded, alerted on or told apart.
So telemetry with no `OTEL_SERVICE_NAME` (or `service.name` in
`OTEL_RESOURCE_ATTRIBUTES`) refuses to boot, exactly like an invalid host
pattern. So does `OTEL_EXPORTER_OTLP_PROTOCOL=grpc`: only the
HTTP/protobuf exporter is installed - gRPC would put `grpcio` in every
image for a transport an ingress cannot route - and ignoring the variable
would leave an HTTP exporter pointed at a port speaking gRPC, visible
only as exports that never arrive.

**That both signals describe one service.** Traces and metrics share a
single `Resource`, rather than building one each from the same
variables: two would be equal today and drift the first time a detector
or an attribute is added to one call site and not the other, at which
point a service's traces and its metrics stop being the same service to
anything reading them.

**Which HTTP conventions to speak.** The instrumentation still defaults
to the pre-stable names (`http.method`, a millisecond
`http.server.duration`) and emits the stable ones
(`http.request.method`, a second-valued `http.server.request.duration`)
only for a process that opts in. This app opts in, by defaulting
`OTEL_SEMCONV_STABILITY_OPT_IN=http` - a `setdefault`, so a fleet
mid-migration can still ask for `http/dup` and get both name sets. It is
the one environment variable this app writes rather than reads, because
the opt-in is read once per process by the instrumentation and there is
no argument to pass it through.

### Where the instrumentation sits

`FastAPIInstrumentor.instrument_app` wraps FastAPI's _entire_ middleware
stack, error handling included, so an unhandled exception is a failed
span carrying the exception event rather than a missing one. It sits
inside this app's own wrappers, though (see "Composition root"), and that
is a deliberate trade rather than an oversight: a server span is worth
its cost only with the matched route on it, and nothing outside FastAPI
knows which route a request will reach. The price is one blind spot - a
request rejected by the body cap _before_ routing is logged with its ID
and never traced, the only response of this app's that telemetry does not
see.

**Probe traffic is excluded.** Every layer in front of a deployment polls
`/livez`, `/readyz` and `/healthz` several times a minute forever; traced,
they would outnumber real requests in the trace store and pull the
latency histogram toward the cost of returning a constant. The exclusion
is expressed as a suffix match, not an anchored one, because the URL the
instrumentation matches against still carries whatever `root_path` the
deployment runs under - the same reversal problem `get_route_path` solves
elsewhere, on a string that has already been turned back into a URL. A
deployment's own exclusions go in the standard
`OTEL_PYTHON_EXCLUDED_URLS` and are _added_ to these, via
`Settings.telemetry_excluded_urls`: left to the instrumentation, that
variable replaces the list it is given, so excluding one noisy path of
your own would quietly put the probes back into every trace.

### What is deliberately not here

- **No logs signal.** The app writes its log stream to stdout, where a
  collector's file receiver or the platform's own agent already picks it
  up (see "Request correlation"), and the records carry `trace_id` and
  `span_id` so the join happens at the backend. A second delivery path
  for the same lines would buy nothing and lose them when the process
  dies with a full buffer.
- **No runtime or process metrics.** CPU, memory and restarts are what
  the platform measures about a container, from outside, whether or not
  the process agrees. The app reports what only the app knows.
- **No hand-written counters.** There are none to write yet, and the
  instrumentation covers every request. When a fork needs one, it creates
  it from `metrics.get_meter(__name__)` - the API resolves to a no-op
  when telemetry is off, so a new counter needs no flag of its own.

`configure_telemetry` is called from `app.main` for the reason
`configure_logging` is, and it is the same reason twice: providers are
one per process, so installing them is the entry point's business and
never a library's. An app embedded in a service that already exports
telemetry keeps that service's providers and its own trace context. Both
providers flush through the SDK's own `atexit` hook, which is why nothing
in the lifespan drains them - a lifespan runs per application, and these
are process-wide.

Two costs worth knowing. Sampling defaults to "keep everything"
(`ParentBased(AlwaysOn)`), which is right for a blueprint and wrong for
a busy service: turn it down with `OTEL_TRACES_SAMPLER` rather than by
touching code. And instrumenting any app in the process patches
Starlette's `BackgroundTask` globally, upstream's doing, so a second
app in the same process with telemetry off still has traced background
tasks.

### The development collector

Compose runs an OpenTelemetry Collector beside Caddy, and `proxy-backend`
exports to it by default - the one service that does, so the feature is
reachable without editing anything. It is the same argument the Caddy
sidecar makes for compression: the thing a deployment relies on should be
visible in development rather than described. The app talks OTLP to a
collector it can reach, and the collector decides where telemetry goes;
in development that is a `debug` exporter printing to
`docker compose logs -f otel-collector`, and pointing it at a real
backend is an edit to `.devcontainer/otel-collector.yaml` alone. The
image is the `contrib` distribution precisely so that edit never becomes
an image change.

`master` deliberately stays off: it is the container that runs the test
suite, whose servers inherit its environment, and a suite whose behavior
depends on whether a sidecar is up fails for the wrong reasons. Setting
the two `OTEL_*` variables in `.devcontainer/.env` includes it - and
sends `proxy-backend` elsewhere too, since the same variable overrides
its default.

The endpoint the app dials lives in Compose and the address the collector
binds lives in the collector's own config: two files, two syntaxes, one
fact. `tests/test_telemetry.py` pins them against each other, the way
`tests/test_node_version_consistency.py` pins the two places a Node
version appears.

`tests/test_telemetry.py` covers the application half in two halves of
its own: in-memory providers for what the instrumentation records, and a
real uvicorn exporting over OTLP to a stub collector the test parses,
because an in-memory exporter proves the instrumentation and nothing
about the transport.

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

Mounted **last**, so real routes always take precedence, and under
`STATIC_URL_PATH` (`/static`, `src/app/templating.py`) rather than at
`/`, which would make the mount a catch-all. That prefix is load-bearing,
not cosmetic: a `Mount` matches every path beneath it with `Match.FULL`,
and Starlette only reaches its trailing-slash redirect once _no_ route has
matched. Mounted at `/`, the assets therefore swallowed the whole URL
space and silently disabled that redirect site-wide - `/healthz/` and
`/docs/` answered 404 rather than pointing at the canonical path, with
`/` the single exception, because the index route matched it before the
mount was reached. `tests/test_api.py` pins the redirect across pages,
docs, schema, API and probes, since the bug is a property of the route
table and invisible from any one route.

Nothing hard-codes the prefix: templates reach assets through
`url_for('static', path=...)`, which derives the URL from the mount and
adds any `root_path` (see "URL generation" above), so moving the mount
moves every reference with it.

Mounted **without** `html=True`: its `index.html`/`404.html`
special-casing belonged to an all-static frontend, and misses must
instead raise 404s for the branded handler above.

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

The lifespan deliberately does not configure logging: that is
deployment policy, claimed by the process entry point (`app.main` - see
"Request correlation" above), and a lifespan that reconfigured it would
run inside every host that mounts this app, test runners included.
Importing the _package_ stays side-effect free; only importing
`app.main` takes ownership of process-wide logging. Several apps in one
process therefore have nothing left to contend for - whoever owns the
entry point owns logging, the one process-wide service per-app
isolation never covered.

What the lifespan does own is the startup echo: the settings the
instance actually booted with, logged once. `app.config` refuses to
boot on invalid settings, and that strictness is only auditable if the
configuration that survived is visible in the log. The one value the
echo counts rather than names is the trusted-host allowlist: it can
carry internal hostnames, and a log line outlives the process that
wrote it (aggregators, bug reports, support tickets), so the echo
answers "how many hosts survived validation" and leaves "which ones" to
the deployment's own configuration.

### Bounded graceful shutdown (`.devcontainer/Dockerfile`)

Shutdown is only half the app's business: the lifespan handler runs after
uvicorn has stopped accepting connections and drained the ones still open,
and how long uvicorn is willing to wait for that is a server flag, not an
app setting. Its default is _no_ limit - one request that never finishes
(a slow client, a stuck upstream, an idle streaming response) keeps the
process alive indefinitely after SIGTERM. Under an orchestrator that
inverts the intent of a rolling deploy: the replica hangs until the
termination grace period expires, then SIGKILL severs every connection,
including the ones that were draining cleanly. So the distribution image sets
Uvicorn's native `UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN` environment value
(default 20 seconds).

The value is load-bearing only in relation to the orchestrator's own
grace period - Kubernetes `terminationGracePeriodSeconds` (30s by
default), `docker stop --time` (10s by default). Keep it _below_ that
period, so the process decides when to give up and exits with its logs
flushed instead of being killed; raising it above the grace period
restores the original failure. Deployments whose requests legitimately
outlive 20s must raise both, in that order.

`tests/test_graceful_shutdown.py` pins the relationship in both
directions: that the image's environment carries a finite timeout, and that
uvicorn actually abandons an in-flight request once it expires.

## Distribution image (`.devcontainer/Dockerfile`)

Effectively every production deployment of this app sits behind an
ingress or a TLS terminator, so the image has to be deployable behind one
without a command override. It uses Uvicorn's public `UVICORN_*` environment
interface directly for every server setting: host, port, root path, proxy
headers, trusted proxy addresses, graceful-shutdown timeout, concurrency limit
and server header. `WEBSITE_*` is reserved for application settings and Compose
topology; there is no second image-specific server vocabulary to translate.

The reverse-proxy subset is `UVICORN_ROOT_PATH`, `UVICORN_PROXY_HEADERS` and
`UVICORN_FORWARDED_ALLOW_IPS`. They default to Uvicorn's behavior - no prefix,
proxy-header handling enabled and loopback only - so a directly exposed
container is unchanged; left at those defaults behind a proxy, the site
advertises an `http://` canonical link for an HTTPS deployment, logs the
proxy's address as every client's, and drops the URL prefix from every link it
generates (see "URL generation" above).

Development uses exactly the same contract. Its prefixed listener is a
dedicated `proxy-backend` Compose service, separate from the `master`
container's direct listener. That process boundary is what lets the backend
receive `UVICORN_ROOT_PATH` without leaking the prefix into direct development
or the test servers `master` launches. Caddy and the backend read the same
root-path value, and the backend trusts only Caddy's pinned Compose-network
address (see [QUICKSTART.md](QUICKSTART.md)).

The command is an `ENTRYPOINT`, not a `CMD`, so run-time arguments are
_appended_ to Uvicorn's rather than replacing the whole command:
`docker run <image> --root-path /shop`, or a Kubernetes `args:`, works
without knowing what the image runs. Command-line values take precedence over
`UVICORN_*` environment values. The entrypoint is the exec-form
`["uvicorn", "app.main:app"]`: Uvicorn is PID 1 directly, with no shell and no
project-specific configuration translation layer.
Setting `ENTRYPOINT` also clears the `python3` `CMD` inherited from the
base image, so nothing declares a `CMD` here; `docker run --entrypoint sh`
is how you run something else.

Two non-`UVICORN_*` values sit beside them, both because a container's
stdout is read by a machine and not by the person who started it:
`PYTHONUNBUFFERED=1`, so a SIGKILL cannot take an 8 KB pipe buffer of log
lines with it, and `LOG_FORMAT=json`, so the aggregator in front of the
deployment gets structured records. Shipping the JSON choice as image
environment rather than as the code default is what keeps a derived
project from editing a template-owned file to get it (see "Request
correlation" above); `docker run -e LOG_FORMAT=text` reads `docker logs`
by hand.

`tests/test_reverse_proxy_config.py` covers both halves of this, the dev
topology and the image's, and the image's behaviorally: there is no Docker in
the dev container, so it runs the exec-form entrypoint with the environment
defaults the Dockerfile declares, and asserts on what the running app then
generates. Uvicorn is lock-pinned, so those behavioral tests are also the
upgrade gate: a future release that changes the public environment contract
fails CI before it can change a deployed image. See also "Bounded graceful
shutdown" above.

### Backpressure (`UVICORN_LIMIT_CONCURRENCY`)

Uvicorn accepts without limit by default, so a burst is taken in full and the
process grows until the kernel OOM-kills it - losing the requests already in
flight along with the ones that caused it. The image sets a ceiling instead:
past it, uvicorn answers 503 from the protocol layer, before the application
is reached, which is a response a load balancer can retry elsewhere while the
replica keeps serving what it already accepted.

The value bounds **connections, not requests in flight**. Uvicorn compares it
against the open-connection count and the task count, whichever is larger, so
an idle keep-alive connection holds a slot exactly like a running request
does. A browser opens several connections per origin, so the default of 512 is
on the order of 85 simultaneous visitors per replica, not 512 - size it
against peak concurrent connections and raise it (or add replicas) rather than
trimming it toward the request rate. Idle slots return after
`--timeout-keep-alive`, 5 seconds by default.

### No `Server` header (`UVICORN_SERVER_HEADER`)

Uvicorn sends `Server: uvicorn` by default. The image turns it off: naming the
stack only helps someone matching a deployment against known issues, and gains
the deployment nothing - the same reasoning behind the response headers in
`src/app/middleware.py`. `Date` stays on; HTTP caches need it and it
identifies nothing.

## Compression

Compression is the reverse proxy's job, like HSTS above, and for a concrete
reason: it is CPU-bound work, and in-process compression would run on
uvicorn's event loop, stalling every other request that worker is handling.
There is deliberately no `GZipMiddleware` in `src/app/factory.py`.

The dev Caddy sidecar therefore sets `encode zstd gzip`, and a production
ingress is expected to do the same. **A directly exposed container serves
everything uncompressed** - one of the few places where the image alone is not
a complete deployment.

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
