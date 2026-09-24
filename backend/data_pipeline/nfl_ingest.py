"""NFL game ingestion through ESPN's public site API.

ESPN's football box score is shaped differently from its basketball one:
a player's stats are split across several named categories (passing,
rushing, receiving, fumbles, ...) instead of one flat stat line, and a
player can appear in more than one category (a QB who also rushed).
Stats are therefore gathered per athlete across every category for
their team before being validated, rather than parsed group-by-group
like the NBA pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Game, Player, PlayerGameStatsNFL, Team
from data_pipeline.espn import ESPNClient, ESPNError
from data_pipeline.espn_common import (
    IngestionError,
    TeamPayload,
    competitor_score,
    season_label,
    team_external_id,
)
from data_pipeline.espn_common import status_state as _status_state
from data_pipeline.espn_common import team_payload as _team_payload


class GamePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=32)
    season: int = Field(ge=1920)
    datetime: datetime
    status_state: str = Field(pattern=r"^(scheduled|in_progress|final)$")
    home_team: TeamPayload
    visitor_team: TeamPayload
    home_score: int | None = None
    visitor_score: int | None = None


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
    passing_completions: int = Field(default=0, ge=0)
    passing_attempts: int = Field(default=0, ge=0)
    passing_yards: int = Field(default=0)
    passing_touchdowns: int = Field(default=0, ge=0)
    interceptions: int = Field(default=0, ge=0)
    rushing_attempts: int = Field(default=0, ge=0)
    rushing_yards: int = Field(default=0)
    rushing_touchdowns: int = Field(default=0, ge=0)
    receptions: int = Field(default=0, ge=0)
    receiving_targets: int = Field(default=0, ge=0)
    receiving_yards: int = Field(default=0)
    receiving_touchdowns: int = Field(default=0, ge=0)
    fumbles_lost: int = Field(default=0, ge=0)
    player: PlayerPayload


def _season_label(season: int) -> str:
    return season_label("NFL", season)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _split_completions_attempts(value: Any) -> tuple[int, int]:
    """ESPN reports passing completions/attempts as one "C/ATT" string."""
    if isinstance(value, str) and "/" in value:
        completions, _, attempts = value.partition("/")
        return _int(completions), _int(attempts)
    return 0, 0


def _group_athletes_by_id(team_box: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Merge every stat category for a team's box score by athlete id.

    A player can appear in multiple categories (passing + rushing for a
    QB), so this returns each athlete's raw info plus a per-category
    dict of stat name -> value, keyed by category name so that e.g. the
    "YDS" key in "passing" is never confused with "YDS" in "rushing".
    """
    athletes: dict[int, dict[str, Any]] = {}
    for group in team_box.get("statistics", []):
        category = group.get("name", "")
        # ESPN sends machine names in "keys" ("passingYards") and display names in
        # "labels" ("YDS"); the stat mapping below is written against the labels.
        key_names = group.get("labels") or group.get("keys", [])
        for entry in group.get("athletes", []):
            athlete = entry.get("athlete", entry)
            athlete_id = int(athlete["id"])
            raw_values = entry.get("stats", entry.get("statistics", []))
            values = dict(zip(key_names, raw_values, strict=False))
            bucket = athletes.setdefault(athlete_id, {"athlete": athlete, "categories": {}})
            bucket["categories"][category] = values
    return athletes


def _stats_payload(athlete_id: int, bucket: dict[str, Any], team_id: int) -> StatsPayload:
    athlete = bucket["athlete"]
    categories: dict[str, dict[str, Any]] = bucket["categories"]
    passing = categories.get("passing", {})
    rushing = categories.get("rushing", {})
    receiving = categories.get("receiving", {})
    fumbles = categories.get("fumbles", {})

    completions, attempts = _split_completions_attempts(passing.get("C/ATT"))
    position = athlete.get("position", {})
    return StatsPayload(
        id=athlete_id,
        passing_completions=completions,
        passing_attempts=attempts,
        passing_yards=_int(passing.get("YDS")),
        passing_touchdowns=_int(passing.get("TD")),
        interceptions=_int(passing.get("INT")),
        rushing_attempts=_int(rushing.get("CAR")),
        rushing_yards=_int(rushing.get("YDS")),
        rushing_touchdowns=_int(rushing.get("TD")),
        receptions=_int(receiving.get("REC")),
        receiving_targets=_int(receiving.get("TGTS")),
        receiving_yards=_int(receiving.get("YDS")),
        receiving_touchdowns=_int(receiving.get("TD")),
        fumbles_lost=_int(fumbles.get("LOST")),
        player=PlayerPayload(
            id=athlete_id,
            first_name=athlete.get("firstName") or athlete["displayName"].split()[0],
            last_name=athlete.get("lastName") or athlete["displayName"].split()[-1],
            position=position.get("abbreviation") if isinstance(position, dict) else position,
            jersey_number=athlete.get("jersey"),
            team_id=team_id,
        ),
    )


class ESPNNFLClient:
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
                else self._client.summary("football", "nfl", event_id)
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
                home_score=competitor_score(home),
                visitor_score=competitor_score(visitor),
            )
            stats: list[StatsPayload] = []
            for team_box in raw.get("boxscore", {}).get("players", []):
                team_id = int(team_box["team"]["id"])
                for athlete_id, bucket in _group_athletes_by_id(team_box).items():
                    stats.append(_stats_payload(athlete_id, bucket, team_id))
            return game, stats
        except (ESPNError, KeyError, StopIteration, TypeError, ValueError, ValidationError) as exc:
            if isinstance(exc, ESPNError):
                raise IngestionError("ESPN rejected or could not serve the NFL summary") from exc
            raise IngestionError("Invalid ESPN NFL summary payload") from exc


def _upsert_team(db: Session, payload: TeamPayload) -> Team:
    external_id = team_external_id("NFL", payload.id)
    team = db.scalar(select(Team).where(Team.external_id == external_id))
    if team is None:
        team = Team(external_id=external_id, sport="NFL")
        db.add(team)
    team.name = payload.full_name
    team.abbreviation = payload.abbreviation
    team.sport = "NFL"
    return team


def ingest_game(db: Session, game: GamePayload, stats: list[StatsPayload]) -> int:
    home_team = _upsert_team(db, game.home_team)
    away_team = _upsert_team(db, game.visitor_team)
    db.flush()
    record = db.scalar(select(Game).where(Game.external_id == str(game.id)))
    if record is None:
        record = Game(external_id=str(game.id))
        db.add(record)
    record.sport = "NFL"
    record.season = _season_label(game.season)
    record.home_team_id = home_team.id
    record.away_team_id = away_team.id
    record.start_time = game.datetime
    record.status = game.status_state
    record.home_score = game.home_score
    record.away_score = game.visitor_score
    db.flush()
    for stat in stats:
        player = db.scalar(select(Player).where(Player.external_id == str(stat.player.id)))
        if player is None:
            # A box score only says who a player played for that day, so it seeds a brand-new
            # player but never overwrites the current team/position/status, which the roster
            # sync (data_pipeline/espn_directory.py) owns. Otherwise ingesting an old game
            # would move a traded player back to his former team.
            player = Player(
                external_id=str(stat.player.id),
                sport="NFL",
                position=stat.player.position,
                team_id=home_team.id if stat.player.team_id == game.home_team.id else away_team.id,
                active=True,
            )
            db.add(player)
        player.name = f"{stat.player.first_name} {stat.player.last_name}"
        db.flush()
        line = db.scalar(select(PlayerGameStatsNFL).where(
            PlayerGameStatsNFL.player_id == player.id, PlayerGameStatsNFL.game_id == record.id
        ))
        if line is None:
            line = PlayerGameStatsNFL(player_id=player.id, game_id=record.id)
            db.add(line)
        line.passing_completions = stat.passing_completions
        line.passing_attempts = stat.passing_attempts
        line.passing_yards = stat.passing_yards
        line.passing_touchdowns = stat.passing_touchdowns
        line.interceptions = stat.interceptions
        line.rushing_attempts = stat.rushing_attempts
        line.rushing_yards = stat.rushing_yards
        line.rushing_touchdowns = stat.rushing_touchdowns
        line.receptions = stat.receptions
        line.receiving_targets = stat.receiving_targets
        line.receiving_yards = stat.receiving_yards
        line.receiving_touchdowns = stat.receiving_touchdowns
        line.fumbles_lost = stat.fumbles_lost
    db.flush()
    return len(stats)


def run(game_id: str, summary_payload: dict[str, Any] | None = None) -> int:
    from app.db.session import SessionLocal

    settings = get_settings()
    client = ESPNNFLClient(settings.nfl_api_timeout_seconds)
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
    parser = argparse.ArgumentParser(description="Ingest one NFL game from ESPN")
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
