# uv installs the locked dependencies below. A named stage rather than a
# direct COPY --from=<image>: Dependabot only bumps FROM lines.
FROM ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa AS uv

# Pinned to the same Python line as requires-python in pyproject.toml;
# Dependabot bumps both tags and digests (see .github/dependabot.yml).
FROM python:3.14-slim@sha256:d3400aa122fa42cf0af0dbe8ec3091b047eac5c8f7e3539f7135e86d855dc015

COPY --from=uv /uv /uvx /usr/local/bin/

# ARG, not ENV: apt stays non-interactive during this build only, and nothing
# leaks into the final image or its children.
ARG DEBIAN_FRONTEND=noninteractive

# Update apt packages. Clean up in the same RUN: a later layer can't shrink
# this one, so the package lists must never be committed to it.
RUN apt-get update \
    && apt-get full-upgrade -y \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install the runtime python packages at the exact versions in uv.lock (the
# single source of truth) into the system interpreter - no venv indirection
# inside a container. Bind mounts (BuildKit): the two files are only needed
# during this RUN and never become image layers - build from the repo root,
# see README.md. --inexact keeps what uv didn't install (pip). ENV, not ARG:
# the child images run uv sync against the same environment.
ENV UV_PROJECT_ENVIRONMENT=/usr/local
RUN --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-cache --inexact --only-group runtime
