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
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js - NodeSource pins the major, apt resolves the latest 26.x
RUN curl -fsSL https://deb.nodesource.com/setup_26.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Frontend lint/format tools at the exact versions in package-lock.json (the
# single source of truth, Dependabot-bumped). Installed to a fixed prefix -
# not /workspace, which the devcontainer hides behind a bind mount - and
# exposed on PATH so plain `prettier` / `eslint` work anywhere.
COPY package.json package-lock.json /opt/npm-tools/
RUN npm ci --prefix /opt/npm-tools --no-audit --no-fund \
    && npm cache clean --force
ENV PATH="/opt/npm-tools/node_modules/.bin:${PATH}"

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
