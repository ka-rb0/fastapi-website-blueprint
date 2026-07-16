# Agent image

## How to build the image

- `cd <repo-root>`
- `docker build --no-cache -f .devcontainer/docker_files/03_agent/Dockerfile -t fastapi-website-blueprint-agent-image .`

## To quickly test the image

- `docker run --rm -it fastapi-website-blueprint-agent-image /bin/bash`

## Family Tree

- _python:slim_
  - _fastapi-website-blueprint-base-image_
    - _fastapi-website-blueprint-dev-image_
      - **fastapi-website-blueprint-agent-image**
