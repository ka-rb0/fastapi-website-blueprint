"""HTTP route collections."""

from .api import HEALTH_PATH
from .api import router as api_router
from .pages import create_pages_router

__all__ = ["HEALTH_PATH", "api_router", "create_pages_router"]
