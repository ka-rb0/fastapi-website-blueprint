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

Docker Compose builds the `agent` target for `master` and the smaller `dev`
target for the proxy backend. `agent` already builds through `dev`, so their
layers are shared. Opening an existing Dev Container starts or attaches to its
existing containers; it does not run a fresh image build. An explicit rebuild
evaluates the Dockerfile but reuses unchanged BuildKit cache layers.

The application source is bind-mounted at `/workspace`, and Compose sets
`PYTHONPATH=/workspace/src`.

## Development reverse proxy

Compose starts Caddy and a dedicated reload-enabled Uvicorn backend for it.
They are development services, not part of the image build graph or the
distribution image. The backend uses the same native `UVICORN_*` settings as
the distribution image; keeping it separate prevents its URL prefix from
affecting direct development and test processes in `master`:

```text
http://localhost:$WEBSITE_EXTERNAL_PORT
  └──→ master:$UVICORN_PORT

https://proxy.localhost:$WEBSITE_PROXY_HTTPS_PORT
  └──→ Caddy
       └── strips $UVICORN_ROOT_PATH
           └──→ proxy-backend:$WEBSITE_PROXY_BACKEND_PORT
```

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
  --env UVICORN_PORT=11111 \
  --publish 11111:11111 \
  fastapi-website-blueprint:distribution
```

Behind an ingress or a TLS-terminating proxy, name the site and the proxy:

```bash
docker run --rm --init \
  --env WEBSITE_TRUSTED_HOSTS=www.example.com \
  --env UVICORN_ROOT_PATH=/shop \
  --env UVICORN_PROXY_HEADERS=true \
  --env UVICORN_FORWARDED_ALLOW_IPS=10.0.0.0/8 \
  --publish 8000:8000 \
  fastapi-website-blueprint:distribution
```

Without the last two, the app would advertise an `http://` canonical link for
an HTTPS site, log the proxy's address as every client's and generate URLs
that miss the prefix - see "Distribution image" in
[../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

Any Uvicorn flag can be appended instead. The image's exec-form `ENTRYPOINT`
is Uvicorn itself, and command-line values take precedence over `UVICORN_*`
environment values:

```bash
docker run --rm --init --publish 8000:8000 \
  fastapi-website-blueprint:distribution --root-path /shop --log-level warning
```

To run something other than the server, override the entrypoint
(`docker run --entrypoint sh ...`).

The container runs as an unprivileged user and includes a health check for
`/readyz`, one of the probe routes that answer whatever `Host` a probe sends -
`WEBSITE_TRUSTED_HOSTS` does not have to name the pod's own address.

## Published images

[publish.yml](../.github/workflows/publish.yml) builds this same
`distribution` target on GitHub Actions and pushes it to
`ghcr.io/<owner>/<repo>` as a multi-platform image (linux/amd64 and
linux/arm64):

| Trigger        | Tags published           |
| -------------- | ------------------------ |
| push to `main` | `main`, `sha-<short>`    |
| push `v1.2.3`  | `1.2.3`, `1.2`, `latest` |
| pull request   | none - build only        |

The pull-request build publishes nothing; it exists so a broken Dockerfile or
an unbuildable lockfile fails the PR instead of `main`. Prereleases
(`v1.2.3-rc.1`) publish their exact version only - they do not move `1.2` or
`latest`.

`sha-<short>` is published from `main` only, deliberately. A release tag is cut
on a commit `main` already carries, so publishing it from tag runs too would
rebuild that commit and repoint `sha-<short>` at a second, different digest -
the build timestamp label alone is enough to change it. Two images of one
commit is expected for the same reason: `main` and `latest` can differ byte for
byte while describing identical source.

Every published digest is signed with a build provenance attestation and an
SPDX SBOM, and the workflow re-pulls and boots the image before going green -
see [GitHub Setup](../docs/GITHUB_SETUP.md) for how to verify them yourself.

Cutting a release is therefore just a tag, on a commit that is already on
`main` - the workflow refuses to publish one that is not:

```bash
git tag v1.2.3 && git push origin v1.2.3
```

Pull and run a published image (`docker login ghcr.io` first while the package
is private - see [GitHub Setup](../docs/GITHUB_SETUP.md)):

```bash
docker run --rm --init \
  --publish 8000:8000 \
  ghcr.io/<owner>/<repo>:latest
```

Every published digest is signed with the build workflow's own identity, so
you can confirm an image was built here before you run it:

```bash
gh attestation verify oci://ghcr.io/<owner>/<repo>:latest -R <owner>/<repo>
```

See [GitHub Setup](../docs/GITHUB_SETUP.md) for what that proves.

Deployments reachable under a real host name must additionally set
`WEBSITE_TRUSTED_HOSTS`; the default trusts only local names, so any other
`Host` header gets a 400.
