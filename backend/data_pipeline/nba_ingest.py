"""NBA game ingestion through ESPN's public site API."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Game, Player, PlayerGameStats, Team
from data_pipeline.espn import ESPNClient, ESPNError


class IngestionError(RuntimeError):
    """Raised when ESPN data cannot be fetched or validated."""


class TeamPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=100)
    abbreviation: str = Field(min_length=2, max_length=10)


class GamePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=32)
    season: int = Field(ge=1946)
    datetime: datetime
    status_state: str = Field(pattern=r"^(scheduled|in_progress|final)$")
    home_team: TeamPayload
    visitor_team: TeamPayload


class PlayerPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(gt=0)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    position: str | None = Field(default=None, max_length=10)
    jersey_number: str | int | None = None
    team_id: int = Field(gt=0)


class StatsPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(gt=0)
    min: str | int | float | None = None
    pts: int = Field(default=0, ge=0)
    reb: int = Field(default=0, ge=0)
    ast: int = Field(default=0, ge=0)
    stl: int = Field(default=0, ge=0)
    blk: int = Field(default=0, ge=0)
    turnover: int = Field(default=0, ge=0)
    fga: int = Field(default=0, ge=0)
    fg3a: int = Field(default=0, ge=0)
    player: PlayerPayload


def _parse_minutes(value: str | int | float | None) -> float:
    if value is None or value == "" or value == "-":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    value = value.strip()
    if not value:
        return 0.0
    iso_match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?", value)
    if iso_match:
        hours, minutes, seconds = iso_match.groups(default="0")
        return int(hours) * 60 + int(minutes) + float(seconds) / 60
    try:
        if ":" in value:
            minutes, seconds = value.split(":", maxsplit=1)
            return int(minutes) + int(seconds) / 60
        return float(value)
    except (TypeError, ValueError) as exc:
        raise IngestionError(f"Invalid minutes value: {value!r}") from exc


def _season_label(season: int) -> str:
    return f"{season}-{str(season + 1)[-2:]}"


def _team_payload(raw: dict[str, Any]) -> TeamPayload:
    team = raw.get("team", raw)
    return TeamPayload(
        id=int(team["id"]),
        name=team.get("name") or team["displayName"],
        full_name=team.get("displayName") or team["name"],
        abbreviation=team.get("abbreviation") or team.get("shortDisplayName", "NBA"),
    )


def _status_state(raw: dict[str, Any]) -> str:
    status = raw.get("status")
    if not isinstance(status, dict):
        competitions = raw.get("competitions", [])
        status = competitions[0].get("status") if competitions else None
    state = status.get("type", {}).get("state") if isinstance(status, dict) else None
    if state in {"pre", "post", "in"}:
        return {"pre": "scheduled", "post": "final", "in": "in_progress"}[state]
    raise IngestionError("ESPN summary has no recognized game status")


def _stat_value(values: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in values:
            return values[key]
    return 0


def _stats_payload(raw: dict[str, Any], team_id: int, key_names: list[str]) -> StatsPayload:
    values = dict(zip(key_names, raw.get("statistics", raw.get("stats", [])), strict=False))
    athlete = raw.get("athlete", raw)
    position = athlete.get("position", {})
    return StatsPayload(
        id=int(athlete["id"]),
        min=_stat_value(values, ("MIN", "minutes")),
        pts=int(_stat_value(values, ("PTS", "points")) or 0),
        reb=int(_stat_value(values, ("REB", "rebounds")) or 0),
        ast=int(_stat_value(values, ("AST", "assists")) or 0),
        stl=int(_stat_value(values, ("STL", "steals")) or 0),
        blk=int(_stat_value(values, ("BLK", "blocks")) or 0),
        turnover=int(_stat_value(values, ("TO", "turnovers")) or 0),
        fga=int(_stat_value(values, ("FGA", "fieldGoalsAttempted")) or 0),
        fg3a=int(_stat_value(values, ("3PA", "threePointersAttempted")) or 0),
        player=PlayerPayload(
            id=int(athlete["id"]),
            first_name=athlete.get("firstName") or athlete["displayName"].split()[0],
            last_name=athlete.get("lastName") or athlete["displayName"].split()[-1],
            position=position.get("abbreviation") if isinstance(position, dict) else position,
            jersey_number=athlete.get("jersey"),
            team_id=team_id,
        ),
    )


class ESPNNBAClient:
    def __init__(self, timeout: float = 20.0, summary_factory: Callable[..., Any] | None = None):
        self._client = ESPNClient(timeout=timeout)
        self._summary_factory = summary_factory

    def close(self) -> None:
        self._client.close()

    def get_game(
        self, event_id: str, summary_payload: dict[str, Any] | None = None
    ) -> tuple[GamePayload, list[StatsPayload]]:
        try:
            raw = summary_payload or (
                self._summary_factory(event_id)
                if self._summary_factory
                else self._client.summary("basketball", "nba", event_id)
            )
            header = raw["header"]
            competition = header["competitions"][0]
            competitors = competition["competitors"]
            home = next(item for item in competitors if item["homeAway"] == "home")
            visitor = next(item for item in competitors if item["homeAway"] == "away")
            home_team = _team_payload(home)
            visitor_team = _team_payload(visitor)
            game = GamePayload(
                id=str(header["id"]),
                season=int(header.get("season", {}).get("year") or competition["season"]["year"]),
                datetime=datetime.fromisoformat(
                    header["competitions"][0]["date"].replace("Z", "+00:00")
                ),
                status_state=_status_state(header),
                home_team=home_team,
                visitor_team=visitor_team,
            )
            stats: list[StatsPayload] = []
            for team_box in raw.get("boxscore", {}).get("players", []):
                team_id = int(team_box["team"]["id"])
                for group in team_box.get("statistics", []):
                    key_names = group.get("keys", [])
                    stats.extend(
                        _stats_payload(player, team_id, key_names)
                        for player in group.get("athletes", [])
                    )
            return game, stats
        except (ESPNError, KeyError, StopIteration, TypeError, ValueError, ValidationError) as exc:
            if isinstance(exc, ESPNError):
                raise IngestionError("ESPN rejected or could not serve the NBA summary") from exc
            raise IngestionError("Invalid ESPN NBA summary payload") from exc


def _upsert_team(db: Session, payload: TeamPayload) -> Team:
    team = db.scalar(select(Team).where(Team.external_id == str(payload.id)))
    if team is None:
        team = Team(external_id=str(payload.id), sport="NBA")
        db.add(team)
    team.name = payload.full_name
    team.abbreviation = payload.abbreviation
    team.sport = "NBA"
    return team


def ingest_game(db: Session, game: GamePayload, stats: list[StatsPayload]) -> int:
    home_team = _upsert_team(db, game.home_team)
    away_team = _upsert_team(db, game.visitor_team)
    db.flush()
    record = db.scalar(select(Game).where(Game.external_id == str(game.id)))
    if record is None:
        record = Game(external_id=str(game.id))
        db.add(record)
    record.sport = "NBA"
    record.season = _season_label(game.season)
    record.home_team_id = home_team.id
    record.away_team_id = away_team.id
    record.start_time = game.datetime
    record.status = game.status_state
    db.flush()
    for stat in stats:
        player = db.scalar(select(Player).where(Player.external_id == str(stat.player.id)))
        if player is None:
            player = Player(external_id=str(stat.player.id), sport="NBA")
            db.add(player)
        player.name = f"{stat.player.first_name} {stat.player.last_name}"
        player.position = stat.player.position
        player.team_id = home_team.id if stat.player.team_id == game.home_team.id else away_team.id
        player.active = True
        db.flush()
        line = db.scalar(select(PlayerGameStats).where(
            PlayerGameStats.player_id == player.id, PlayerGameStats.game_id == record.id
        ))
        if line is None:
            line = PlayerGameStats(player_id=player.id, game_id=record.id)
            db.add(line)
        line.minutes = _parse_minutes(stat.min)
        line.points = stat.pts
        line.rebounds = stat.reb
        line.assists = stat.ast
        line.steals = stat.stl
        line.blocks = stat.blk
        line.turnovers = stat.turnover
        line.field_goal_attempts = stat.fga
        line.three_point_attempts = stat.fg3a
    db.flush()
    return len(stats)


def run(game_id: str, summary_payload: dict[str, Any] | None = None) -> int:
    from app.db.session import SessionLocal

    settings = get_settings()
    client = ESPNNBAClient(settings.nba_api_timeout_seconds)
    db = SessionLocal()
    try:
        game, stats = client.get_game(game_id, summary_payload)
        count = ingest_game(db, game, stats)
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        client.close()
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest one NBA game from ESPN")
    parser.add_argument("--game-id", type=str, required=True)
    parser.add_argument(
        "--payload-stdin",
        action="store_true",
        help="Read an ESPN summary JSON object from stdin (useful when Docker egress is blocked)",
    )
    args = parser.parse_args()
    summary_payload = json.load(sys.stdin) if args.payload_stdin else None
    print(
        f"Upserted {run(args.game_id, summary_payload)} player stat lines "
        f"for game {args.game_id}."
    )


if __name__ == "__main__":
    main()
