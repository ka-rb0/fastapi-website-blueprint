"""HTTP route collections."""

from .api import router as api_router
from .pages import create_pages_router
from .probes import PROBE_PATHS
from .probes import router as probes_router

__all__ = ["PROBE_PATHS", "api_router", "create_pages_router", "probes_router"]
