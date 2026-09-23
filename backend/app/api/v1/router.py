"""Aggregates all v1 routes into a single router.

main.py only needs to know about this module, not about individual
endpoint files — new endpoints get added here, not in main.py.
"""

from fastapi import APIRouter

from app.api.v1 import health, players

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(players.router)
