# How to build the image

Build from the **repo root** so `pyproject.toml` and `uv.lock` (the dependency
sources of truth) are in the build context:

- `cd <repo-root>`
- `docker build --no-cache -f .devcontainer/docker_files/01_base/Dockerfile -t fastapi-website-blueprint-base-image .`

# To quickly test the image

- `docker run --rm -it fastapi-website-blueprint-base-image /bin/bash`

# Family Tree

- _python:slim_
  - **fastapi-website-blueprint-base-image**
