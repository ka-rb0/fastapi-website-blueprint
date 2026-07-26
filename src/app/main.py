"""Uvicorn entry point for the FastAPI Website Blueprint."""

from .config import Settings
from .factory import create_app

# Environment loading belongs at the executable boundary. Importing
# ``app.factory`` remains side-effect free, while ``uvicorn app.main:app``
# retains the conventional ready-to-serve application object.
app = create_app(Settings.from_env())

__all__ = ["app", "create_app"]
