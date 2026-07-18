# Node.js comes from the official image - digest-pinned and Dependabot-bumped
# like the base images, unlike the NodeSource installer script this replaces.
# A named stage rather than a direct COPY --from=<image>: Dependabot only
# bumps FROM lines. Same Debian release (trixie) as the python base image, so
# the copied binary finds matching shared libraries. The major must match
# engines.node in package.json (the single source of truth, which CI reads);
# tests/test_node_version_consistency.py enforces that.
FROM node:26-slim@sha256:715e55e4b84e4bb0ff48e49b398a848f08e55daed8eb6a0ea1839ae53bc57583 AS node

# Use the locally built image (see ../README.md for the build order)
FROM fastapi-website-blueprint-base-image

# ARG, not ENV: apt stays non-interactive during this build only, and nothing
# leaks into the final image or its children.
ARG DEBIAN_FRONTEND=noninteractive

# Install extra apt-get packages (cleanup in the same RUN so the package
# lists never become part of the layer)
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

# Install Node.js from the pinned stage above. The node binary needs only
# libatomic1 (installed above) beyond what the python base image ships;
# npm/npx are the standard symlinks into the bundled node_modules/npm
# (recreated by hand - COPY would dereference them).
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# npm-based lint/format tools at the exact versions in package-lock.json (the
# single source of truth, Dependabot-bumped). Installed to a fixed prefix -
# not /workspace, which the devcontainer hides behind a bind mount - and
# exposed on PATH so plain `prettier` / `eslint` work anywhere.
COPY package.json package-lock.json /opt/npm-tools/
RUN npm ci --prefix /opt/npm-tools --no-audit --no-fund \
    && npm cache clean --force
ENV PATH="/opt/npm-tools/node_modules/.bin:${PATH}"
# Let Node-based config files resolve packages from the same baked-in prefix.
# CommonJS resolution (including createRequire from ESM) honors NODE_PATH.
ENV NODE_PATH=/opt/npm-tools/node_modules

# Install the dev python packages (pytest, mypy, ruff, playwright, …) at the
# exact versions in uv.lock - same pattern and reasoning as the base image.
RUN --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-cache --inexact

# Install playwright's headless browser plus its system deps (this runs its
# own apt-get update, hence the cleanup)
RUN playwright install chromium --with-deps \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
