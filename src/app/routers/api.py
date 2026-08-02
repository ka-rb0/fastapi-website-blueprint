"""JSON API routes."""

from fastapi import APIRouter

from ..schemas import ShoutPayload, ShoutReply

# A module-level constant is safe here because these routes hold no per-app
# state (include_router copies them into each app). Anything touching
# app-owned resources belongs in a create_*_router factory - see
# app.routers.pages for the pattern.
router = APIRouter(prefix="/api")

# The health route's full path, as a request carries it (prefix included, no
# root_path). Named because the composition root exempts it from the Host
# allowlist - see HostValidationMiddleware. tests/test_api.py pins that the
# constant still names a route this router actually serves.
HEALTH_PATH = "/api/health"


@router.get("/health")
async def health() -> dict[str, str]:
    """Report that the application can serve requests."""
    return {"status": "ok"}


@router.post("/shout")
async def shout(payload: ShoutPayload) -> ShoutReply:
    """Reply with the supplied text uppercased."""
    return ShoutReply(text=payload.text.upper())
