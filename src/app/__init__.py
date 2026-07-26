"""FastAPI Website Blueprint application package."""

from .config import Settings
from .factory import create_app

__all__ = ["Settings", "create_app"]
