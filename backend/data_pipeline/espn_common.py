"""Payload shapes and parsing shared by every ESPN sport-ingestion pipeline.

A team's payload shape and how ESPN encodes game status are identical
across sports (ESPN's site API is one family of endpoints); each
sport's own stat shape is not, so it stays in that sport's ingest
module rather than here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IngestionError(RuntimeError):
    """Raised when ESPN data cannot be fetched or validated."""


class TeamPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=100)
    abbreviation: str = Field(min_length=2, max_length=10)


def team_payload(raw: dict[str, Any]) -> TeamPayload:
    team = raw.get("team", raw)
    return TeamPayload(
        id=int(team["id"]),
        name=team.get("name") or team["displayName"],
        full_name=team.get("displayName") or team["name"],
        abbreviation=team.get("abbreviation") or team.get("shortDisplayName", team.get("name", "")),
    )


def status_state(raw: dict[str, Any]) -> str:
    status = raw.get("status")
    if not isinstance(status, dict):
        competitions = raw.get("competitions", [])
        status = competitions[0].get("status") if competitions else None
    state = status.get("type", {}).get("state") if isinstance(status, dict) else None
    if state in {"pre", "post", "in"}:
        return {"pre": "scheduled", "post": "final", "in": "in_progress"}[state]
    raise IngestionError("ESPN summary has no recognized game status")
