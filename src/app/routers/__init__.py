"""HTTP route collections."""

from .api import router as api_router
from .pages import create_pages_router

__all__ = ["api_router", "create_pages_router"]
