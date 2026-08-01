# syntax=docker/dockerfile:1

# uv installs the locked dependencies below. A named stage rather than a
# direct COPY --from=<image>: Dependabot only bumps FROM lines.
FROM ghcr.io/astral-sh/uv:0.12.0@sha256:606e70c71c852d03f611b1e56a195d08648507018a7057fab82c4974c4eae105 AS uv

# Node.js comes from the official image - digest-pinned and Dependabot-bumped
# like the other base images. The Debian release (trixie) matches the Python
# image, so the copied binary finds matching shared libraries. The major must
# match engines.node in package.json; tests/test_node_version_consistency.py
# enforces that.
FROM node:26-slim@sha256:715e55e4b84e4bb0ff48e49b398a848f08e55daed8eb6a0ea1839ae53bc57583 AS node

# Pinned to the same Python line as requires-python in pyproject.toml;
# Dependabot bumps both tags and digests (see .github/dependabot.yml).
FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6 AS base

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

# uvicorn's access logger writes to stdout, which is a pipe under Docker, so
# Python block-buffers it in 8 KB chunks: `docker logs` shows nothing until a
# chunk fills, and everything still buffered is lost when the process is
# SIGKILLed (OOM kill, failed liveness probe) - exactly when the last lines
# matter most. ENV rather than the CMD's `python -u`, so anything else run in
# the container (docker exec, the HEALTHCHECK probe) logs promptly as well.
ENV PYTHONUNBUFFERED=1

# Overridable at run time: docker run -e WEBSITE_INTERNAL_PORT=... -p ...
ENV WEBSITE_INTERNAL_PORT=8000
# Deployments must also set WEBSITE_TRUSTED_HOSTS to the site's public host
# name(s): the code's default (see Settings.trusted_hosts in
# src/app/config.py) trusts only local names, so real traffic gets a 400
# until it is set. Keep 127.0.0.1 in the list - the HEALTHCHECK below
# probes it.
# EXPOSE is build-time metadata only; a run-time WEBSITE_INTERNAL_PORT
# override changes the bind port, not this line.
EXPOSE ${WEBSITE_INTERNAL_PORT}

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
ENV WEBSITE_GRACEFUL_SHUTDOWN_SECONDS=20

# Nothing needs root at run time: uvicorn binds a high port and the code is
# read-only, so drop to an unprivileged user.
RUN useradd --system --no-create-home app
USER app

# The base stage has no curl/wget, so probe /api/health with the stdlib.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['WEBSITE_INTERNAL_PORT'] + '/api/health', timeout=4)"

# Shell form allows WEBSITE_INTERNAL_PORT and the shutdown timeout to resolve
# at run time; exec makes uvicorn PID 1, so it receives the stop signal itself.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${WEBSITE_INTERNAL_PORT}\" --timeout-graceful-shutdown \"${WEBSITE_GRACEFUL_SHUTDOWN_SECONDS}\""]
