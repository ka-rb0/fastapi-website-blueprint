"""JSON API routes."""

from fastapi import APIRouter

from ..schemas import ShoutPayload, ShoutReply

# A module-level constant is safe here because these routes hold no per-app
# state (include_router copies them into each app). Anything touching
# app-owned resources belongs in a create_*_router factory - see
# app.routers.pages for the pattern.
router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict[str, str]:
    """Report that the application can serve requests."""
    return {"status": "ok"}


@router.post("/shout")
async def shout(payload: ShoutPayload) -> ShoutReply:
    """Reply with the supplied text uppercased."""
    return ShoutReply(text=payload.text.upper())
