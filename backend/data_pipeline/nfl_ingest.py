"""NFL game ingestion through ESPN's public site API.

ESPN's football box score is shaped differently from its basketball one:
a player's stats are split across several named categories (passing,
rushing, receiving, fumbles, ...) instead of one flat stat line, and a
player can appear in more than one category (a QB who also rushed).
Stats are therefore gathered per athlete across every category for
their team before being validated, rather than parsed group-by-group
like the NBA pipeline.

Field goal distances are not in the box score, so each kick is read from the
game's play-by-play and attributed to a kicker. The kicks must add up to every
kicker's box-score FG line or the game is rejected as inconsistent.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import FieldGoalKick, Game, Player, PlayerGameStatsNFL, Team
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
    field_goals_made: int = Field(default=0, ge=0)
    field_goal_attempts: int = Field(default=0, ge=0)
    extra_points_made: int = Field(default=0, ge=0)
    extra_point_attempts: int = Field(default=0, ge=0)
    kick_return_touchdowns: int = Field(default=0, ge=0)
    punt_return_touchdowns: int = Field(default=0, ge=0)
    player: PlayerPayload

    @model_validator(mode="after")
    def _made_kicks_cannot_exceed_attempts(self) -> StatsPayload:
        for made, attempted, name in (
            (self.passing_completions, self.passing_attempts, "completions"),
            (self.field_goals_made, self.field_goal_attempts, "field goals"),
            (self.extra_points_made, self.extra_point_attempts, "extra points"),
        ):
            if made > attempted:
                raise ValueError(f"{name} made ({made}) exceeds attempted ({attempted})")
        return self


class KickPayload(BaseModel):
    """One field goal attempt, attributed to the kicker who took it."""

    model_config = ConfigDict(extra="ignore")

    play_id: str = Field(min_length=1, max_length=64)
    kicker_id: int = Field(gt=0)
    distance: int = Field(ge=1, le=99)
    result: str = Field(pattern=r"^(made|missed|blocked)$")


def _season_label(season: int) -> str:
    return season_label("NFL", season)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _split_completions_attempts(value: Any) -> tuple[int, int]:
    """ESPN reports made/attempted pairs as one "made/attempted" string.

    Passing is "24/37" (C/ATT), and the kicking group's FG and XP are the same shape.
    """
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
    kicking = categories.get("kicking", {})
    kick_returns = categories.get("kickReturns", {})
    punt_returns = categories.get("puntReturns", {})

    completions, attempts = _split_completions_attempts(passing.get("C/ATT"))
    field_goals_made, field_goal_attempts = _split_completions_attempts(kicking.get("FG"))
    extra_points_made, extra_point_attempts = _split_completions_attempts(kicking.get("XP"))
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
        field_goals_made=field_goals_made,
        field_goal_attempts=field_goal_attempts,
        extra_points_made=extra_points_made,
        extra_point_attempts=extra_point_attempts,
        kick_return_touchdowns=_int(kick_returns.get("TD")),
        punt_return_touchdowns=_int(punt_returns.get("TD")),
        player=PlayerPayload(
            id=athlete_id,
            first_name=athlete.get("firstName") or athlete["displayName"].split()[0],
            last_name=athlete.get("lastName") or athlete["displayName"].split()[-1],
            position=position.get("abbreviation") if isinstance(position, dict) else position,
            jersey_number=athlete.get("jersey"),
            team_id=team_id,
        ),
    )


_KICK_RESULTS = {
    "Field Goal Good": "made",
    "Field Goal Missed": "missed",
    "Blocked Field Goal": "blocked",
}
_KICK_TEXT = re.compile(r"^\s*(?P<kicker>[A-Z]\.[^\d]+?) (?P<distance>\d+) yard field goal")


def _short_name(athlete: dict[str, Any]) -> str:
    """The "D.Zvada" form play text uses for a player."""
    first = athlete.get("firstName") or athlete["displayName"].split()[0]
    last = athlete.get("lastName") or " ".join(athlete["displayName"].split()[1:])
    return f"{first[0]}.{last}"


def _kickers_by_team(raw: dict[str, Any]) -> dict[int, dict[int, str]]:
    """Each team's kickers from the box score's kicking group: team -> athlete id -> "D.Zvada"."""
    kickers: dict[int, dict[int, str]] = {}
    for team_box in raw.get("boxscore", {}).get("players", []):
        team_id = int(team_box["team"]["id"])
        for group in team_box.get("statistics", []):
            if group.get("name") != "kicking":
                continue
            for entry in group.get("athletes", []):
                athlete = entry.get("athlete", entry)
                kickers.setdefault(team_id, {})[int(athlete["id"])] = _short_name(athlete)
    return kickers


def _parse_kicks(raw: dict[str, Any], stats: list[StatsPayload]) -> list[KickPayload] | None:
    """Every field goal attempt in the game's plays, or None when it has no play data.

    Distance is the play's `statYardage`; a blocked kick reports 0 there, so its distance
    comes from the play text. The kicking team is the play's `start.team` (`teamParticipants`
    lists both teams). Raises IngestionError when a kick cannot be attributed or the kicks do
    not add up to the box score, rather than storing a distance-scored line that is wrong.
    """
    drives = raw.get("drives")
    if not isinstance(drives, dict):
        return None
    all_drives = list(drives.get("previous", []))
    if isinstance(drives.get("current"), dict):
        all_drives.append(drives["current"])

    kickers = _kickers_by_team(raw)
    kicks: list[KickPayload] = []
    for drive in all_drives:
        for play in drive.get("plays", []):
            result = _KICK_RESULTS.get(play.get("type", {}).get("text"))
            if result is None:
                continue
            match = _KICK_TEXT.match(play.get("text", ""))
            distance = play.get("statYardage") or (match and int(match["distance"]))
            team_kickers = kickers.get(int(play["start"]["team"]["id"]), {})
            named = [
                athlete_id
                for athlete_id, short in team_kickers.items()
                if match and short == match["kicker"]
            ]
            candidates = named or list(team_kickers)
            if len(candidates) != 1 or not distance:
                raise IngestionError(f"Cannot attribute field goal play {play.get('id')}")
            kicks.append(
                KickPayload(
                    play_id=str(play["id"]),
                    kicker_id=candidates[0],
                    distance=distance,
                    result=result,
                )
            )

    for stat in stats:
        own = [kick for kick in kicks if kick.kicker_id == stat.id]
        if (sum(k.result == "made" for k in own), len(own)) != (
            stat.field_goals_made,
            stat.field_goal_attempts,
        ):
            raise IngestionError(
                f"Field goal plays for athlete {stat.id} do not match the box score "
                f"({stat.field_goals_made}/{stat.field_goal_attempts})"
            )
    return kicks


class ESPNNFLClient:
    def __init__(self, timeout: float = 20.0, summary_factory: Callable[..., Any] | None = None):
        self._client = ESPNClient(timeout=timeout)
        self._summary_factory = summary_factory

    def close(self) -> None:
        self._client.close()

    def get_game(
        self, event_id: str, summary_payload: dict[str, Any] | None = None
    ) -> tuple[GamePayload, list[StatsPayload], list[KickPayload] | None]:
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
            return game, stats, _parse_kicks(raw, stats)
        except (
            ESPNError,
            IngestionError,
            KeyError,
            StopIteration,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            if isinstance(exc, ESPNError):
                raise IngestionError("ESPN rejected or could not serve the NFL summary") from exc
            if isinstance(exc, IngestionError):
                raise
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


def ingest_game(
    db: Session,
    game: GamePayload,
    stats: list[StatsPayload],
    kicks: list[KickPayload] | None = None,
) -> int:
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
        line.field_goals_made = stat.field_goals_made
        line.field_goal_attempts = stat.field_goal_attempts
        line.extra_points_made = stat.extra_points_made
        line.extra_point_attempts = stat.extra_point_attempts
        line.kick_return_touchdowns = stat.kick_return_touchdowns
        line.punt_return_touchdowns = stat.punt_return_touchdowns
    db.flush()
    if kicks is not None:
        _sync_kicks(db, record, kicks)
    return len(stats)


def _sync_kicks(db: Session, game: Game, kicks: list[KickPayload]) -> None:
    """Make the game's stored kicks mirror the payload: upsert by play id, drop stale ones."""
    kept: set[str] = set()
    for kick in kicks:
        player = db.scalar(select(Player).where(Player.external_id == str(kick.kicker_id)))
        row = db.scalar(
            select(FieldGoalKick).where(FieldGoalKick.external_play_id == kick.play_id)
        )
        if row is None:
            row = FieldGoalKick(external_play_id=kick.play_id)
            db.add(row)
        row.player_id = player.id
        row.game_id = game.id
        row.distance = kick.distance
        row.result = kick.result
        kept.add(kick.play_id)
    for stale in db.scalars(select(FieldGoalKick).where(FieldGoalKick.game_id == game.id)):
        if stale.external_play_id not in kept:
            db.delete(stale)
    db.flush()


def run(game_id: str, summary_payload: dict[str, Any] | None = None) -> int:
    from app.db.session import SessionLocal

    settings = get_settings()
    client = ESPNNFLClient(settings.nfl_api_timeout_seconds)
    db = SessionLocal()
    try:
        game, stats, kicks = client.get_game(game_id, summary_payload)
        count = ingest_game(db, game, stats, kicks)
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
