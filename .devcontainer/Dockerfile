# syntax=docker/dockerfile:1

# uv installs the locked dependencies below. A named stage rather than a
# direct COPY --from=<image>: Dependabot only bumps FROM lines.
FROM ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc AS uv

# Node.js comes from the official image - digest-pinned and Dependabot-bumped
# like the other base images. The Debian release (trixie) matches the Python
# image, so the copied binary finds matching shared libraries. The major must
# match engines.node in package.json; tests/test_node_version_consistency.py
# enforces that.
FROM node:26-slim@sha256:4ebb5ace66f15a24c14c492e01a8beeed4fddf970a856109f5126e703e5fe503 AS node

# Pinned to the same Python line as requires-python in pyproject.toml;
# Dependabot bumps both tags and digests (see .github/dependabot.yml).
FROM python:3.14-slim@sha256:a7fb1e634c4a578f9e0bd6327f11a3cde11b7a9395f48e24360c0988bcc5c2bc AS base

COPY --from=uv /uv /uvx /usr/local/bin/

# Deliberately no `apt-get full-upgrade` here: the digest above is the single
# source of this image's package versions, so builds stay reproducible.
# Debian security patches arrive as Dependabot digest bumps (upstream rebuilds
# the Python images on base-image updates) instead of drifting in unpinned at
# build time - merge those weekly PRs promptly.

# Install the runtime Python packages ([project.dependencies], which
# --no-default-groups narrows the sync to) at the exact versions in uv.lock
# (the single source of truth) into the system interpreter - no venv
# indirection inside a container. Bind mounts (BuildKit) keep the lockfiles
# out of image layers. --inexact keeps what uv didn't install (pip). ENV,
# not ARG: child stages run uv sync against the same environment.
ENV UV_PROJECT_ENVIRONMENT=/usr/local
RUN --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-cache --inexact --no-default-groups

# The dev and agent stages form the desktop-development branch. The
# distribution stage below branches directly from base, so BuildKit skips all
# dev and agent work when distribution is selected.
FROM base AS dev

# ARG, not ENV: apt stays non-interactive during this stage only, and nothing
# leaks into the resulting image or its children.
ARG DEBIAN_FRONTEND=noninteractive

# Install extra apt packages. Exact pins would eventually break because Debian
# drops superseded versions and Dependabot has no apt ecosystem. The versions
# effectively track the digest-pinned Debian release of the base image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    nano \
    wget \
    curl \
    git \
    fd-find \
    dos2unix \
    jq \
    libatomic1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js from the pinned source stage. npm/npx are standard symlinks
# into the bundled node_modules/npm and are recreated because COPY would
# dereference them.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# npm-based lint/format tools at the exact versions in package-lock.json.
# Install to a fixed prefix rather than /workspace, which the devcontainer
# hides behind a bind mount.
COPY package.json package-lock.json /opt/npm-tools/
RUN npm ci --prefix /opt/npm-tools --no-audit --no-fund \
    && npm cache clean --force
ENV PATH="/opt/npm-tools/node_modules/.bin:${PATH}"
# Let Node-based config files resolve packages from the baked-in prefix.
ENV NODE_PATH=/opt/npm-tools/node_modules

# Install the dev Python packages (pytest, mypy, ruff, playwright, etc.) at the
# exact versions in uv.lock.
RUN --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-cache --inexact

# Install Playwright's headless browser plus its system dependencies.
RUN playwright install chromium --with-deps \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

FROM dev AS agent

# The agent CLIs float deliberately: they self-update, their vendors only
# support the current release, and there is no lockfile Dependabot could bump.
# Docker caches RUN commands without checking whether these remote scripts
# changed; rebuild with `--no-cache-filter agent` to refresh them explicitly.
RUN curl -fsSL https://claude.ai/install.sh | bash
RUN curl -fsSL https://chatgpt.com/codex/install.sh | sh

# Claude CLI is installed in /root/.local/bin/claude.
ENV PATH="/root/.local/bin:${PATH}"

# Keep distribution last so it is the safe default when --target is omitted.
FROM base AS distribution

# Copy only the application source into the runtime image.
COPY src/app /src/app

# No "${PYTHONPATH}:" prefix: an empty leading entry would put the current
# working directory on sys.path.
ENV PYTHONPATH=/src

# The app writes its whole log stream to stdout (see "Request correlation" in
# docs/ARCHITECTURE.md), which is a pipe under Docker, so Python block-buffers
# it in 8 KB chunks: `docker logs` shows nothing until a chunk fills, and
# everything still buffered is lost when the process is SIGKILLed (OOM kill,
# failed liveness probe) - exactly when the last lines matter most. ENV rather
# than a `python -u` in the entrypoint, so anything else run in the container
# (docker exec, the HEALTHCHECK probe) logs promptly as well.
ENV PYTHONUNBUFFERED=1

# Uvicorn's public environment interface is the distribution image's one
# server-configuration contract. Keeping these as UVICORN_* values means the
# image, the development proxy backend and a bare `uvicorn app.main:app` all
# speak the same language; the exec-form entrypoint below needs no shell
# translation layer. Every value remains overridable at run time.
ENV UVICORN_HOST=0.0.0.0
ENV UVICORN_PORT=8000
# Deployments must also set WEBSITE_TRUSTED_HOSTS to the site's public host
# name(s): the code's default (see Settings.trusted_hosts in
# src/app/config.py) trusts only local names, so real traffic gets a 400
# until it is set. The health route is exempt from that check, so the
# HEALTHCHECK below and an orchestrator's probes keep working whatever the
# allowlist says (see "Trusted hosts" in docs/ARCHITECTURE.md).
# EXPOSE is build-time metadata only; a run-time UVICORN_PORT
# override changes the bind port, not this line.
EXPOSE ${UVICORN_PORT}

# Reverse-proxy wiring. These default to Uvicorn's own behavior, so a directly
# exposed container behaves exactly as before, and they matter as soon as an
# ingress or TLS terminator sits in front:
#
#   UVICORN_ROOT_PATH           the URL prefix the proxy serves the app under
#                               and strips before forwarding (e.g. /shop).
#                               Without it every URL the app generates - the
#                               canonical link, the shout form's action - omits
#                               the prefix and points outside the site.
#   UVICORN_FORWARDED_ALLOW_IPS comma-separated peers whose X-Forwarded-* this
#                               app honors. Uvicorn's default trusts only the
#                               loopback, which is never the proxy in a
#                               container: until this names the ingress, an
#                               HTTPS site advertises an http:// canonical link
#                               and every access line logs the proxy's address
#                               as the client's (see "URL generation" in
#                               docs/ARCHITECTURE.md). Set it to the proxy's
#                               real address or subnet, not "*" - "*" lets any
#                               client forge both.
ENV UVICORN_ROOT_PATH=""
ENV UVICORN_PROXY_HEADERS=true
ENV UVICORN_FORWARDED_ALLOW_IPS=127.0.0.1

# How long uvicorn may spend draining in-flight requests after SIGTERM.
# uvicorn's own default is *no* limit: it waits for every open connection to
# finish, so one slow or stuck request keeps the container alive until the
# orchestrator's termination grace period runs out and SIGKILL cuts the
# connections mid-response - the opposite of draining them, and a rolling
# deploy that stalls one grace period per replica. Bounding the wait here
# turns that into a clean exit. Keep this value *below* the orchestrator's
# grace period (Kubernetes `terminationGracePeriodSeconds`, 30s by default;
# `docker stop --time`, 10s by default) so uvicorn is the one that decides
# when to give up; raise both together for long-running requests.
ENV UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN=20

# Backpressure. Uvicorn's default is *no* limit, so a burst of traffic is
# accepted in full and the process grows until the kernel OOM-kills it - the
# whole replica dies, in-flight requests included, instead of the excess being
# turned away. Past this number uvicorn answers 503 straight from the protocol
# layer, before the application is reached: a load balancer can retry that
# elsewhere, and the replica keeps serving what it already accepted.
#
# The number bounds *connections*, not requests in flight: uvicorn compares it
# against the open-connection count and the task count, whichever is larger,
# so an idle keep-alive connection occupies a slot just as much as a running
# request does (uvicorn/protocols/http/h11_impl.py). Size it against peak
# concurrent connections, therefore - a browser opens several per origin, so
# 512 is roughly 85 simultaneous visitors per replica, not 512. Idle slots come
# back after --timeout-keep-alive (5s by default). Set it too low and ordinary
# traffic gets 503s, so raise it (or add replicas) rather than trimming it to
# the request rate.
ENV UVICORN_LIMIT_CONCURRENCY=512

# Don't advertise the server software. Uvicorn sends `Server: uvicorn` by
# default, which hands a scanner the stack to look up known issues for and
# gains a deployment nothing in return - the same reasoning that shapes the
# response headers in src/app/middleware.py. The `Date` header stays on: HTTP
# caches need it, and it identifies nothing.
ENV UVICORN_SERVER_HEADER=false

# Nothing needs root at run time: uvicorn binds a high port and the code is
# read-only, so drop to an unprivileged user.
RUN useradd --system --no-create-home app
USER app

# The base stage has no curl/wget, so probe /api/health with the stdlib.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['UVICORN_PORT'] + '/api/health', timeout=4)"

# ENTRYPOINT rather than CMD, so `docker run <image> --root-path /shop` (or a
# Kubernetes `args:`) appends Uvicorn flags; command-line values take
# precedence over UVICORN_* environment values. Exec form makes Uvicorn PID 1
# directly, with no shell process or project-specific option translation.
# Setting ENTRYPOINT also clears the `python3` CMD inherited from the base
# image, so nothing declares a CMD here; use `docker run --entrypoint sh` to
# run something else.
ENTRYPOINT ["uvicorn", "app.main:app"]
