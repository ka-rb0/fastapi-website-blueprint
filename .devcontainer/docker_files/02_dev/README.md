# Dev image

## How to build the image

Build from the **repo root** so the lockfiles (`pyproject.toml` + `uv.lock`,
`package.json` + `package-lock.json` - the dependency sources of truth) are in
the build context:

- `cd <repo-root>`
- `docker build --no-cache -f .devcontainer/docker_files/02_dev/Dockerfile -t fastapi-website-blueprint-dev-image .`

## To quickly test the image

- `docker run --rm -it fastapi-website-blueprint-dev-image /bin/bash`

## Family Tree

- _python:slim_
  - _fastapi-website-blueprint-base-image_
    - **fastapi-website-blueprint-dev-image**
