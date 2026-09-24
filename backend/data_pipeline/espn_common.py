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


def season_label(sport: str, year: int) -> str:
    """Human season label for ESPN's season year.

    ESPN's year is the year a season *ends* for the NBA (2027 is 2026-27) but
    the year it starts for the NFL (2026 is the 2026 season).
    """
    return f"{year - 1}-{str(year)[-2:]}" if sport == "NBA" else str(year)


def competitor_score(competitor: dict[str, Any]) -> int | None:
    """A competitor's score, or None before the game has one.

    Game summaries carry it as a string ("31"), team schedules as an object
    ({"value": 31.0, "displayValue": "31"}).
    """
    score = competitor.get("score")
    if isinstance(score, dict):
        score = score.get("value")
    try:
        return int(float(score))
    except (TypeError, ValueError):
        return None


def team_external_id(sport: str, espn_team_id: int | str) -> str:
    """Namespaced key for teams.external_id.

    ESPN numbers teams per league, so the NBA's Atlanta and the NFL's Atlanta are
    both team 1 while teams.external_id is unique across the whole table.
    """
    return f"{sport.lower()}:{espn_team_id}"
