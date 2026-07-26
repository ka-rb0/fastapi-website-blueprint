"""Uvicorn entry point for the FastAPI Website Blueprint."""

from .config import Settings
from .factory import create_app

# Environment loading belongs at the executable boundary. Importing
# ``app.factory`` remains side-effect free, while ``uvicorn app.main:app``
# retains the conventional ready-to-serve application object.
app = create_app(Settings.from_env())

# Only the served application: import create_app from the package root
# instead - importing this module constructs an env-configured app.
__all__ = ["app"]
