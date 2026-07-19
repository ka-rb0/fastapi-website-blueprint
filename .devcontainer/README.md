# Container images

The project uses one multi-stage Dockerfile for development and distribution.
Build from the repository root so the Python and npm lockfiles and application
source are available in the build context.

## Build graph

```text
uv ──→ base ←── python
       ├──→ dev ←── node
       │     └──→ agent
       └──→ distribution
```

The named stages are:

- `base`: Python plus the locked runtime Python dependencies.
- `dev`: `base` plus Node.js, lint and test tools, and Playwright.
- `agent`: `dev` plus Claude Code and OpenAI Codex.
- `distribution`: `base` plus the application source and production
  runtime configuration.

BuildKit follows the dependency graph. A `distribution` build skips the
`node`, `dev`, and `agent` stages. The `distribution` stage is last, so
it is also the default if `--target` is omitted.

## Build a target

From the repository root:

```bash
docker build \
  --target base \
  --tag fastapi-website-blueprint:base \
  --file .devcontainer/Dockerfile \
  .
```

Replace `base` with `dev`, `agent`, or `distribution` and adjust the tag
as desired. Each command builds its prerequisites automatically; the stages do
not need to be built or tagged in a particular order.

Do not use `--no-cache` for routine builds. Docker reuses unchanged layers,
including the expensive development tools and browser installation.

## Dev container

Docker Compose builds the `agent` target automatically. Opening an existing
Dev Container starts or attaches to its existing container; it does not run a
fresh image build. An explicit rebuild evaluates the Dockerfile but reuses
unchanged BuildKit cache layers.

The application source is bind-mounted at `/workspace`, and Compose sets
`PYTHONPATH=/workspace/src`.

## Refresh the agent CLIs

Docker does not check whether a remote script used by a cached `RUN`
instruction has changed. The Claude Code and Codex installer layers remain
cached until the `agent` stage or one of its prerequisites is invalidated.

To deliberately reinstall only the agent stage:

```bash
docker build \
  --target agent \
  --no-cache-filter agent \
  --tag fastapi-website-blueprint:agent \
  --file .devcontainer/Dockerfile \
  .
```

A Dev Container rebuild after that command can reuse the refreshed local
layers.

## Run the distribution image

Build and run the minimal runtime branch:

```bash
docker build \
  --target distribution \
  --tag fastapi-website-blueprint:distribution \
  --file .devcontainer/Dockerfile \
  .

docker run --rm --init \
  --publish 8000:8000 \
  fastapi-website-blueprint:distribution
```

Then open <http://localhost:8000/>.

To use a different port:

```bash
docker run --rm --init \
  --env WEBSITE_INTERNAL_PORT=20166 \
  --publish 20166:20166 \
  fastapi-website-blueprint:distribution
```

The container runs as an unprivileged user and includes a health check for
`/api/health`.
