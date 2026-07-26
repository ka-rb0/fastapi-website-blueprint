"""Application startup and shutdown lifecycle."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import Settings
from .templating import STATIC_DIR

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configure process services when an application instance starts."""
    settings: Settings = app.state.settings
    # Startup, not import time: importing the package must not alter the
    # process-wide root logger. basicConfig is still process-global and
    # first-wins: with several apps in one process, the first lifespan to
    # start sets the root log level (see docs/ARCHITECTURE.md).
    logging.basicConfig(level=settings.log_level)
    logger.info("Serving static files from %s", STATIC_DIR)
    yield
