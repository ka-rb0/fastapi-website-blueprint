"""Application-specific exception responses."""

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.templating import Jinja2Templates

# See app.middleware for why the defining private module is the correct source.
from starlette._utils import get_route_path
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response


def register_exception_handlers(app: FastAPI, templates: Jinja2Templates) -> None:
    """Register exception handlers that depend on app-owned resources."""

    @app.exception_handler(404)
    async def branded_404(request: Request, exc: StarletteHTTPException) -> Response:
        """
        Render an HTML 404 for pages while preserving JSON API errors.

        ``get_route_path`` strips ``root_path`` in the same way as FastAPI's
        router, so the API classification also works behind a path-prefixing
        reverse proxy.
        """
        path = get_route_path(request.scope)
        if path != "/api" and not path.startswith("/api/"):
            return templates.TemplateResponse(
                request, "not-found.html", status_code=404
            )
        return await http_exception_handler(request, exc)
