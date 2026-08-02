# Quickstart

## Run the server

### Direct

- Open a terminal and run the following command

```sh
uvicorn app.main:app --host 0.0.0.0 --port $WEBSITE_INTERNAL_PORT --reload
```

- Open an external desktop browser (in your host)
  - Go to `http://localhost:$WEBSITE_EXTERNAL_PORT`
    - e.g. <http://localhost:11110/>

### Through Caddy (reverse proxy)

- Open a terminal and run the following command

```sh
uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "$WEBSITE_INTERNAL_PORT_WITH_REVERSE_PROXY" \
  --reload \
  --root-path "$WEBSITE_REVERSE_PROXY_ROOT_PATH" \
  --proxy-headers \
  --forwarded-allow-ips="$WEBSITE_REVERSE_PROXY_TRUSTED_IP"
```

- Open an external desktop browser (in your host)
  - Go to `https://proxy.localhost:$WEBSITE_EXTERNAL_HTTPS_PORT_WITH_REVERSE_PROXY$WEBSITE_REVERSE_PROXY_ROOT_PATH/`
    - e.g. <https://proxy.localhost:11211/prefix/>

## Good to know

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
  `WEBSITE_TRUSTED_HOSTS` to its public host name(s). `/api/health` is the
  one route exempt from the check, so container healthchecks and Kubernetes
  probes - which address the pod by an IP no allowlist could name - keep
  working whatever you set (see "Trusted hosts" in
  [ARCHITECTURE.md](ARCHITECTURE.md)). Testing from a phone on your
  LAN? The phone addresses the site by this machine's LAN IP, so add that
  IP - not the phone's - or use `"*"` while developing (see
  `.devcontainer/.env.example`).
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
- Importing `app.main` claims process-wide logging, so **the root and Uvicorn
  portions of `uvicorn --log-config` are silently overridden** when you serve
  `app.main:app`; explicitly named non-Uvicorn loggers may retain their
  configuration, potentially producing mixed output. Reshape the claimed logs
  by editing `LOG_FORMAT` in `src/app/observability.py`, or, if the flag has to
  win, serve your own entry point that calls `create_app` without importing
  `app.main` (see "Request correlation" in [ARCHITECTURE.md](ARCHITECTURE.md)).
- `--forwarded-allow-ips="$WEBSITE_REVERSE_PROXY_TRUSTED_IP"` defaults to
  Caddy's pinned Compose-network address (see `docker-compose.yml`), not
  `*`: uvicorn only honors X-Forwarded-For/X-Forwarded-Proto from that one
  peer. Trusting `*` instead would let any client spoof its own IP (breaking
  logging/rate-limiting) or spoof `X-Forwarded-Proto: https` (bypassing
  anything downstream that trusts "this request was HTTPS") - if you reuse
  this pattern behind a different reverse proxy, set
  `WEBSITE_REVERSE_PROXY_TRUSTED_IP` to that proxy's real address instead.
- The distribution image takes the same reverse-proxy settings as the
  command above, as environment variables: `WEBSITE_ROOT_PATH`
  (`--root-path`) and `WEBSITE_PROXY_TRUSTED_IPS` (`--forwarded-allow-ips`,
  with `--proxy-headers` always on). Both default to uvicorn's behavior, so
  a directly exposed container needs neither, and any uvicorn flag can also
  be appended at run time - `docker run <image> --root-path /shop`, or a
  Kubernetes `args:` - because the image's command is an `ENTRYPOINT` and
  the last occurrence of a repeated option wins. That also means
  `docker run <image> sh` no longer opens a shell; use
  `docker run --entrypoint sh <image>`. See "Distribution image" in
  [ARCHITECTURE.md](ARCHITECTURE.md).
- The distribution image stops gracefully within
  `WEBSITE_GRACEFUL_SHUTDOWN_SECONDS` (20 by default), which it passes to
  uvicorn as `--timeout-graceful-shutdown`. Uvicorn without that flag waits
  forever for in-flight connections, so a single stuck request turns every
  rolling-deploy replacement into a SIGKILL once the orchestrator's grace
  period runs out. Keep the value below that grace period
  (`terminationGracePeriodSeconds` in Kubernetes, `docker stop --time`
  elsewhere), and raise the grace period first if your requests need longer
  - see [ARCHITECTURE.md](ARCHITECTURE.md).
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
