"""HTTP route collections."""

from .api import router as api_router
from .pages import create_pages_router
from .probes import PROBE_PATHS, VERSION_PATH, create_version_router
from .probes import router as probes_router

__all__ = [
    "PROBE_PATHS",
    "VERSION_PATH",
    "api_router",
    "create_pages_router",
    "create_version_router",
    "probes_router",
]
