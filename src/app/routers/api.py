"""JSON API routes."""

from fastapi import APIRouter

from ..schemas import ShoutPayload, ShoutReply

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict[str, str]:
    """Report that the application can serve requests."""
    return {"status": "ok"}


@router.post("/shout")
async def shout(payload: ShoutPayload) -> ShoutReply:
    """Reply with the supplied text uppercased."""
    return ShoutReply(text=payload.text.upper())
