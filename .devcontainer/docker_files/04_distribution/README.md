# Distribution image

## How to build the image

Build from the **repo root** so `src/app` (the application code this image
copies in) is in the build context:

- `cd <repo-root>`
- `docker build --no-cache -f .devcontainer/docker_files/04_distribution/Dockerfile -t fastapi-website-blueprint-distribution-image .`

## To quickly test the image

`--init` gives the container a PID 1 that reaps orphans (uvicorn doesn't):

- `docker run --rm --init -p 8000:8000 fastapi-website-blueprint-distribution-image`
  - then open <http://localhost:8000/>
  - a different port: `docker run --rm --init -e WEBSITE_INTERNAL_PORT=20166 -p 20166:20166 fastapi-website-blueprint-distribution-image`
- `docker run --rm -it fastapi-website-blueprint-distribution-image /bin/bash`

## Family Tree

- _python:slim_
  - _fastapi-website-blueprint-base-image_
    - **fastapi-website-blueprint-distribution-image**
