# uv installs the locked dependencies below. A named stage rather than a
# direct COPY --from=<image>: Dependabot only bumps FROM lines.
FROM ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc AS uv

# Pinned to the same Python line as requires-python in pyproject.toml;
# Dependabot bumps both tags and digests (see .github/dependabot.yml).
FROM python:3.14-slim@sha256:d3400aa122fa42cf0af0dbe8ec3091b047eac5c8f7e3539f7135e86d855dc015

COPY --from=uv /uv /uvx /usr/local/bin/

# Deliberately no `apt-get full-upgrade` here: the digest above is the single
# source of this image's package versions, so builds stay reproducible.
# Debian security patches arrive as Dependabot digest bumps (upstream rebuilds
# the python images on base-image updates) instead of drifting in unpinned at
# build time - merge those weekly PRs promptly.

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
