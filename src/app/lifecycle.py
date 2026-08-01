"""Application startup and shutdown lifecycle."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from .config import Settings
from .observability import configure_logging
from .templating import STATIC_DIR

logger = logging.getLogger(__name__)


def create_lifespan(
    settings: Settings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """
    Create a lifespan handler bound to one app's settings.

    A closure, like the pages router, so runtime code never reads
    configuration back off ``app.state`` - state stays an introspection
    point for tests and embedding code only.
    """

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Startup, not import time: importing the package must not reconfigure
        # the process-wide logging module. Logging stays process-global and
        # last-wins, so with several apps in one process the last lifespan to
        # start decides the format and level (see docs/ARCHITECTURE.md).
        configure_logging(settings.log_level)
        logger.info("Serving static files from %s", STATIC_DIR)
        yield

    return lifespan
