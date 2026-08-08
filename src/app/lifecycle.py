"""Application startup and shutdown lifecycle."""

import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from .config import Settings
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
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        # Deliberately no logging configuration here: logging is deployment
        # policy, owned by the process entry point (app.main, or an embedding
        # host's own setup) - a lifespan that reconfigured it would run inside
        # every host that mounts this app (see docs/ARCHITECTURE.md).
        logger.info("Serving static files from %s", STATIC_DIR)
        # Echo the surviving configuration once: app.config refuses to boot on
        # invalid settings, and that strictness is only auditable if what an
        # instance actually booted with is visible in its log. The host
        # allowlist is counted, not named: it is the one setting here whose
        # value can carry internal hostnames, and logs travel further than the
        # deployment does (aggregators, bug reports, support tickets). The
        # count still shows an empty-vs-default-vs-configured allowlist, which
        # is what the echo is for. CodeQL flags the named form as clear-text
        # logging of a secret for the same reason.
        logger.info(
            "Trusted hosts: %d configured; docs %s; request bodies capped at %d bytes",
            len(settings.trusted_hosts),
            "enabled" if settings.docs_enabled else "disabled",
            settings.max_body_bytes,
        )
        yield

    return lifespan
