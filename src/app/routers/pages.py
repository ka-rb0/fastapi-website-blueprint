"""Server-rendered page routes."""

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response


def create_pages_router(templates: Jinja2Templates) -> APIRouter:
    """Create page routes bound to one app's template environment."""
    router = APIRouter(include_in_schema=False)

    @router.head("/")
    @router.get("/")
    async def index(request: Request) -> Response:
        """Render the homepage."""
        return templates.TemplateResponse(request, "index.html")

    return router
