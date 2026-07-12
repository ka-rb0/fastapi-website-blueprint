# Use the locally built image (see ../README.md for the build order)
FROM fastapi-website-blueprint-base-image

# Copy the source code into the container
COPY src/app /src/app

# No "${PYTHONPATH}:" prefix - same reasoning as Dockerfile.master
ENV PYTHONPATH=/src

# Overridable at run time: docker run -e WEBSITE_INTERNAL_PORT=... -p ...
ENV WEBSITE_INTERNAL_PORT=8000
# EXPOSE is build-time metadata only - it documents the default; a run-time
# WEBSITE_INTERNAL_PORT override changes the bind port, not this line.
EXPOSE ${WEBSITE_INTERNAL_PORT}

# Nothing needs root at run time: uvicorn binds a high port and the code is
# read-only, so drop to an unprivileged user.
RUN useradd --system --no-create-home app
USER app

# The base image has no curl/wget - probe /api/health with the stdlib.
# --start-period covers uvicorn's startup before failures start counting.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['WEBSITE_INTERNAL_PORT'] + '/api/health', timeout=4)"

# Shell form so ${WEBSITE_INTERNAL_PORT} resolves at run time
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${WEBSITE_INTERNAL_PORT}\""]
