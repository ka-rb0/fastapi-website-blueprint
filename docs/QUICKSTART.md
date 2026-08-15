# Quickstart

## Run the server

### Direct

- Open a terminal and run the following command

```sh
uvicorn app.main:app --reload
```

Compose supplies `UVICORN_HOST` and `UVICORN_PORT`, the same native server
settings the distribution image uses.

- Open an external desktop browser (in your host)
  - Go to `http://localhost:$WEBSITE_EXTERNAL_PORT`
    - e.g. <http://localhost:11110/>

### Through Caddy (reverse proxy)

The reload-enabled `proxy-backend` service starts with the Dev Container. It
receives `UVICORN_ROOT_PATH`, `UVICORN_PROXY_HEADERS` and
`UVICORN_FORWARDED_ALLOW_IPS` from Compose, exactly like the distribution
image; no second command is needed.

- Open an external desktop browser (in your host)
  - Go to `https://proxy.localhost:$WEBSITE_PROXY_HTTPS_PORT$UVICORN_ROOT_PATH/`
    - e.g. <https://proxy.localhost:11211/prefix/>

## Good to know

- `UVICORN_*` configures the server in development and production;
  `WEBSITE_*` configures the FastAPI application or Compose-only topology.
  Keeping that ownership boundary means there are no aliases or environment
  variables that silently override one another.
- Interactive API docs (Swagger UI): `<url>/docs` is a dev tool and is only
  served when `WEBSITE_ENABLE_DOCS=1`, which the dev container sets by default.
  Therefore don't set it in production!
- The app answers only requests whose `Host` header it trusts and rejects
  the rest with a 400 (`Settings.trusted_hosts` in `src/app/config.py`).
  The allowlist matches _site names_ - what stands in the visitor's URL bar -
  never clients: any device may connect, and in production, listing your
  domain serves every visitor, exactly like nginx's `server_name`. The
  default covers local development, and the dev container adds
  `proxy.localhost` for the Caddy topology; a production deployment must set
  `WEBSITE_TRUSTED_HOSTS` to its public host name(s). The probe routes
  (`/livez`, `/readyz`, `/healthz`) and `/version` are the only ones exempt
  from the check, so container healthchecks, Kubernetes probes and rollout
  checks - which address the pod by an IP no allowlist could name - keep
  working whatever you set (see "Trusted hosts" in
  [ARCHITECTURE.md](ARCHITECTURE.md)). Testing from a phone on your
  LAN? The phone addresses the site by this machine's LAN IP, so add that
  IP - not the phone's - or use `"*"` while developing (see
  `.devcontainer/.env.example`).
  Entries are ASCII host names without a scheme, port or path; DNS names are
  matched case-insensitively. Wildcards have the form `*.example.com` (or
  `"*"` to disable the guard). Starlette's matcher does not currently support
  IPv6 literals, so invalid or unsupported patterns fail at startup instead
  of producing an allowlist that rejects every request.
- Request bodies are capped at 1 MB with a 413 (`Settings.max_body_bytes` in
  `src/app/config.py`, overridable via `WEBSITE_MAX_BODY_BYTES`). The app
  rejects an oversized declared `Content-Length` before routing and counts
  streamed bodies as an endpoint consumes them. The Caddy sidecar enforces
  the same cap at the proxy, which also covers chunked bodies sent to routes
  that never read them. Per-field limits like the shout form's `maxlength`
  only apply after a whole body has been received, so raise either limit
  deliberately when an endpoint needs more.
- Every response carries an `X-Request-ID`, and every log line prints it in
  brackets - uvicorn's access line included, so one ID finds the request and
  everything the app logged while handling it. Send the header yourself (or
  have your gateway send it) and the app keeps your value, as long as it is
  1-64 visible ASCII characters; anything else is replaced with a fresh one
  rather than refused. Lines with no request behind them (startup, shutdown)
  show `[-]`. `LOG_LEVEL` sets the level for the app and uvicorn alike -
  access lines are INFO, so `WARNING` and up silences them too.
- `LOG_FORMAT` picks how each line is rendered: `text` (the default here -
  what you tail in a terminal) or `json`, one object per line for a log
  pipeline. The distribution image sets `json`, so a deployment gets
  structured logs without editing anything; set `LOG_FORMAT=json` in
  `.devcontainer/.env` to see locally what your aggregator will receive, or
  `docker run -e LOG_FORMAT=text` to read `docker logs` by hand. Both
  renderings carry the same fields, request ID included. The fields
  themselves stay in code - `TEXT_LOG_FORMAT` and `JSON_LOG_FIELDS` in
  `src/app/observability.py` - because they are the log schema your
  dashboards match on; edit them there to add or rename a field.
- OpenTelemetry traces and metrics are **off until you name a collector**:
  set `OTEL_EXPORTER_OTLP_ENDPOINT` (e.g. `http://collector:4318`) and
  `OTEL_SERVICE_NAME`, and the app exports the standard HTTP semantics -
  `http.server.request.duration`, `http.server.active_requests`, one server
  span per request carrying `http.route` and the request's `X-Request-ID`.
  Both variables are required together: telemetry with no service name would
  arrive as `unknown_service`, so the app refuses to start instead. Everything
  else is the SDK's own vocabulary and needs no code change - sample down with
  `OTEL_TRACES_SAMPLER`/`OTEL_TRACES_SAMPLER_ARG`, add resource attributes with
  `OTEL_RESOURCE_ATTRIBUTES`, silence it fleet-wide with `OTEL_SDK_DISABLED=true`.
  Only OTLP over HTTP/protobuf is installed, so leave
  `OTEL_EXPORTER_OTLP_PROTOCOL` unset or set it to `http/protobuf`; `grpc`
  fails at startup rather than exporting into the void. The probe routes are
  never traced (they would outnumber real traffic); add your own exclusions
  with `OTEL_PYTHON_EXCLUDED_URLS` and they are added to that, not swapped for
  it. JSON log lines gain `trace_id`/`span_id` while a request is being traced,
  which is how a backend joins a log line to its trace - see "Telemetry" in
  [ARCHITECTURE.md](ARCHITECTURE.md).
- The dev container ships an OpenTelemetry Collector, and the `proxy-backend`
  service already exports to it: browse
  `https://proxy.localhost:$WEBSITE_PROXY_HTTPS_PORT$UVICORN_ROOT_PATH/` and
  watch the spans and metrics arrive with
  `docker compose logs -f otel-collector`. It prints them (
  `.devcontainer/otel-collector.yaml`, `exporters.debug`); point that file at a
  real backend and nothing in the app changes. The direct dev server is off by
  default because the test suite inherits its environment - uncomment the two
  `OTEL_*` lines in `.devcontainer/.env` to include it.
- Importing `app.main` claims process-wide logging, so **the root and Uvicorn
  portions of `uvicorn --log-config` are silently overridden** when you serve
  `app.main:app`; explicitly named non-Uvicorn loggers may retain their
  configuration, potentially producing mixed output. Reshape the claimed logs
  with `LOG_FORMAT` (and the field constants beside it in
  `src/app/observability.py`), or, if the flag has to
  win, serve your own entry point that calls `create_app` without importing
  `app.main` (see "Request correlation" in [ARCHITECTURE.md](ARCHITECTURE.md)).
- `UVICORN_FORWARDED_ALLOW_IPS` is set to Caddy's pinned Compose-network
  address (see `docker-compose.yml`), not `*`: Uvicorn only honors
  X-Forwarded-For/X-Forwarded-Proto from that one peer. Trusting `*` instead
  would let any client spoof its own IP (breaking
  logging/rate-limiting) or spoof `X-Forwarded-Proto: https` (bypassing
  anything downstream that trusts "this request was HTTPS") - if you reuse
  this pattern behind a different reverse proxy, set
  `UVICORN_FORWARDED_ALLOW_IPS` to that proxy's real address instead.
- Development and the distribution image use Uvicorn's native environment
  interface: `UVICORN_ROOT_PATH`, `UVICORN_PROXY_HEADERS` and
  `UVICORN_FORWARDED_ALLOW_IPS`. The image defaults to no prefix, proxy-header
  handling enabled and loopback trusted, matching Uvicorn's defaults, so a
  directly exposed container needs no changes. Any Uvicorn flag can also
  be appended at run time - `docker run <image> --root-path /shop`, or a
  Kubernetes `args:` - because Uvicorn is the image's `ENTRYPOINT` and CLI
  values take precedence over environment values. That also means
  `docker run <image> sh` no longer opens a shell; use
  `docker run --entrypoint sh <image>`. See "Distribution image" in
  [ARCHITECTURE.md](ARCHITECTURE.md).
- The distribution image stops gracefully within
  `UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN` (20 seconds by default). Uvicorn without
  a finite setting waits forever for in-flight connections, so a single stuck
  request turns every rolling-deploy replacement into a SIGKILL once the
  orchestrator's grace period runs out. Keep the value below that grace period
  (`terminationGracePeriodSeconds` in Kubernetes, `docker stop --time`
  elsewhere), and raise the grace period first if your requests need longer
  - see [ARCHITECTURE.md](ARCHITECTURE.md).
- The image caps what it accepts at `UVICORN_LIMIT_CONCURRENCY` (512 by
  default) and answers 503 above it, rather than accepting a burst until the
  container is OOM-killed. The number counts **connections, not requests in
  flight** - an idle keep-alive connection holds a slot, and a browser opens
  several per origin, so 512 is on the order of 85 simultaneous visitors per
  replica. Tune it against peak concurrent connections; if ordinary traffic
  starts seeing 503s, raise it or add replicas.
- Responses carry no `Server` header (`UVICORN_SERVER_HEADER=false`): naming
  the stack only helps someone matching the deployment against known issues.
- Compression belongs to the reverse proxy, like HSTS - it is CPU-bound work
  that would otherwise run on uvicorn's event loop. The Caddy sidecar sets
  `encode zstd gzip`; configure your production ingress to do the same,
  because **a directly exposed container serves everything uncompressed**.
- To preview different screen sizes, press `Ctrl+Shift+M` in the browser's
  developer tools

## Other commands

- [Test & Lint](TEST_AND_LINT.md)
- [Cheatsheet](CHEATSHEET.md)

### Normalize line endings to LF

- `fdfind --type file --exec dos2unix {}`
- `git add --renormalize .`

### Claude

- `claude --version`
- `claude /login`
- `claude -p "Reply exactly: OK"`
