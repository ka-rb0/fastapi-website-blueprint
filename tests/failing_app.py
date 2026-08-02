"""
The deployed app plus one route that raises, served by a real uvicorn.

Exists because the correlation of an unhandled exception's traceback is a
claim about *uvicorn* - that it catches the exception above RequestIDMiddleware
and only then logs "Exception in ASGI application", still inside the request's
context - and the app has no route that would ever produce one. Same standard
as the access-line test in tests/test_request_id.py: a claim about uvicorn's
behavior is driven through uvicorn.

Imported by that test through `uvicorn tests.failing_app:app`, never by the
pytest process, so nothing here runs unless a server is started on it.
"""

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

# Importing app.main is the point, not an implementation detail: it is what
# runs configure_logging, so this server logs exactly the way a deployed one
# does. The module-level `app` below is that same wrapped application.
from app.main import app
from tests.helpers import framework_app

BOOM_PATH = "/boom"


async def boom(request: Request) -> Response:
    """Raise, so uvicorn has an unhandled exception to log a traceback for."""
    raise RuntimeError("kaboom")


# Inserted at the front, not appended, so this route wins whatever else the app
# serves. That is load-bearing today: create_app mounts StaticFiles at "/",
# which matches every path, so an appended route would be unreachable and this
# test would assert against a 404 instead of the 500 it is about. It stays
# correct if that mount ever narrows to /static - the front of the table is
# simply where a test route belongs.
framework_app(app).router.routes.insert(0, Route(BOOM_PATH, boom))
