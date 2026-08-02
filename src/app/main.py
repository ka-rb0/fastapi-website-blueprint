"""Uvicorn entry point for the FastAPI Website Blueprint."""

from .config import Settings
from .factory import create_app
from .observability import configure_logging

# Environment loading belongs at the executable boundary. Importing
# ``app.factory`` remains side-effect free, while ``uvicorn app.main:app``
# retains the conventional ready-to-serve application object.
settings = Settings.from_env()

# Logging is deployment policy, so the executable boundary claims it - not
# create_app or the lifespan, whose side effects would reach into any host
# embedding this app (its pytest capture, its JSON pipeline). Import time is
# the ordering that lets this replace uvicorn's setup: uvicorn configures its
# logging when its Config is constructed and imports this module afterwards.
# A host that never imports app.main keeps its own logging, and can opt in by
# calling configure_logging itself (see docs/ARCHITECTURE.md).
configure_logging(settings.log_level)

app = create_app(settings)

# Only the served application: import create_app from the package root (or its
# defining module) instead - importing this module constructs an env-configured
# app and takes ownership of process-wide logging.
__all__ = ["app"]
