# Building the images

Build from the **repo root** so the lockfiles (`pyproject.toml` + `uv.lock`,
`package.json` + `package-lock.json` - the dependency sources of truth) are in
the build context.

- `cd <repo-root>`
- `docker build --no-cache -f .devcontainer/docker_files/01_base/Dockerfile -t fastapi-website-blueprint-base-image .`
- `docker build --no-cache -f .devcontainer/docker_files/02_dev/Dockerfile -t fastapi-website-blueprint-dev-image .`
- `docker build --no-cache -f .devcontainer/docker_files/03_agent/Dockerfile -t fastapi-website-blueprint-agent-image .`
- `docker build --no-cache -f .devcontainer/docker_files/04_distribution/Dockerfile -t fastapi-website-blueprint-distribution-image .`
