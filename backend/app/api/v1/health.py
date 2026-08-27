"""Health check endpoint.

This exists so we have one real, testable endpoint from the very first
milestone: the frontend can call it to confirm the stack is wired up,
and CI can call it to confirm the container actually boots.
"""

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/health")
def get_health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "environment": settings.environment,
    }
