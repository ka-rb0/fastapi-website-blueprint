# syntax=docker/dockerfile:1

# uv installs the locked dependencies below. A named stage rather than a
# direct COPY --from=<image>: Dependabot only bumps FROM lines.
FROM ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc AS uv

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

# Install the runtime Python packages at the exact versions in uv.lock (the
# single source of truth) into the system interpreter - no venv indirection
# inside a container. Bind mounts (BuildKit) keep the lockfiles out of image
# layers. --inexact keeps what uv didn't install (pip). ENV, not ARG: child
# stages run uv sync against the same environment.
ENV UV_PROJECT_ENVIRONMENT=/usr/local
RUN --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-cache --inexact --only-group runtime

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

# Overridable at run time: docker run -e WEBSITE_INTERNAL_PORT=... -p ...
ENV WEBSITE_INTERNAL_PORT=8000
# EXPOSE is build-time metadata only; a run-time WEBSITE_INTERNAL_PORT
# override changes the bind port, not this line.
EXPOSE ${WEBSITE_INTERNAL_PORT}

# Nothing needs root at run time: uvicorn binds a high port and the code is
# read-only, so drop to an unprivileged user.
RUN useradd --system --no-create-home app
USER app

# The base stage has no curl/wget, so probe /api/health with the stdlib.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['WEBSITE_INTERNAL_PORT'] + '/api/health', timeout=4)"

# Shell form allows WEBSITE_INTERNAL_PORT to resolve at run time.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${WEBSITE_INTERNAL_PORT}\""]
