"""Demo Mode control endpoints."""

import secrets

from fastapi import APIRouter, Header, HTTPException, status

from app.core.config import get_settings
from app.services.demo import reset_demo_state

router = APIRouter(prefix="/demo", tags=["Demo"])


@router.post("/reset")
async def reset_demo(
    x_demo_reset_key: str | None = Header(default=None, alias="X-Demo-Reset-Key"),
) -> dict[str, str]:
    """Reset the in-memory demo state machine after verifying the reset key."""
    settings = get_settings()
    if not x_demo_reset_key or not secrets.compare_digest(
        x_demo_reset_key, settings.demo_reset_key
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid demo reset key.",
        )
    reset_demo_state()
    return {"status": "ok", "message": "Demo reset complete"}
