"""Player, team, injury and schedule directory sync from ESPN's public site API.

Unlike the game-ingestion jobs (one game's box score per run), this job keeps
the *reference data* current: every team's logo and colors, every rostered
player's team/number/position/headshot/bio, the current injury report, and the
regular-season schedule (including scores for games already played). It is
idempotent — rows are upserted by ESPN id — so it is safe to run daily.

Run for one sport or both:

    python -m data_pipeline.espn_directory --sport NBA
    python -m data_pipeline.espn_directory --sport all
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Game, Player, Team
from data_pipeline.espn import ESPNClient, ESPNError
from data_pipeline.espn_common import (
    IngestionError,
    competitor_score,
    season_label,
    status_state,
    team_external_id,
)

# sport -> (ESPN sport path, ESPN league path)
LEAGUES: dict[str, tuple[str, str]] = {
    "NBA": ("basketball", "nba"),
    "NFL": ("football", "nfl"),
}

# Injury-feed entries with this status are roster-move news, not injuries.
_HEALTHY_STATUS = "Active"
_MIN_USEFUL_NOTE_LENGTH = 25


class TeamRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)
    abbreviation: str = Field(min_length=2, max_length=10)
    logo_url: str | None = Field(default=None, max_length=255)
    primary_color: str | None = Field(default=None, max_length=7)


class RosterPlayer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)
    position: str | None = Field(default=None, max_length=10)
    jersey_number: int | None = None
    headshot_url: str | None = Field(default=None, max_length=255)
    height_inches: int | None = None
    weight_lbs: int | None = None
    birth_date: date | None = None
    college: str | None = Field(default=None, max_length=100)
    experience_years: int | None = None
    active: bool = True


class InjuryRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    player_id: int = Field(gt=0)
    status: str = Field(min_length=1, max_length=30)
    type: str | None = Field(default=None, max_length=50)
    note: str | None = None
    reported_at: datetime | None = None


class ScheduledGame(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=32)
    season: str = Field(min_length=1, max_length=10)
    start_time: datetime
    status: str = Field(pattern=r"^(scheduled|in_progress|final)$")
    home_team_id: int = Field(gt=0)
    away_team_id: int = Field(gt=0)
    week: int | None = None
    home_score: int | None = None
    away_score: int | None = None


# ---------------------------------------------------------------------------
# Parsing: ESPN payload -> validated records. No database access.
# ---------------------------------------------------------------------------


def _clean_int(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _utc_naive(value: str) -> datetime:
    """Parse an ESPN ISO timestamp into the naive-UTC form the DB stores."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def parse_teams(raw: dict[str, Any]) -> list[TeamRecord]:
    try:
        entries = raw["sports"][0]["leagues"][0]["teams"]
    except (KeyError, IndexError, TypeError) as exc:
        raise IngestionError("Unexpected ESPN teams payload") from exc

    teams: list[TeamRecord] = []
    for entry in entries:
        team = entry.get("team", entry)
        logos = team.get("logos") or []
        default_logo = next((logo for logo in logos if "default" in logo.get("rel", [])), None)
        logo = default_logo or (logos[0] if logos else {})
        color = team.get("color")
        try:
            teams.append(
                TeamRecord(
                    id=int(team["id"]),
                    name=team.get("displayName") or team["name"],
                    abbreviation=team["abbreviation"],
                    logo_url=logo.get("href"),
                    primary_color=f"#{color}" if color else None,
                )
            )
        except (KeyError, ValueError, ValidationError):
            continue  # an unusable entry (e.g. an all-star squad) shouldn't sink the sync
    return teams


def _roster_athletes(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """NFL rosters arrive grouped (offense/defense/practice squad/...), NBA flat."""
    athletes = raw.get("athletes") or []
    flat: list[dict[str, Any]] = []
    for entry in athletes:
        if isinstance(entry, dict) and "items" in entry:
            flat.extend(entry["items"])
        else:
            flat.append(entry)
    return flat


def _roster_player(athlete: dict[str, Any]) -> RosterPlayer:
    position = athlete.get("position")
    birth = athlete.get("dateOfBirth")
    return RosterPlayer(
        id=int(athlete["id"]),
        name=athlete.get("fullName") or athlete["displayName"],
        position=position.get("abbreviation") if isinstance(position, dict) else None,
        jersey_number=_clean_int(athlete.get("jersey")),
        headshot_url=(athlete.get("headshot") or {}).get("href"),
        height_inches=_clean_int(athlete.get("height")),
        weight_lbs=_clean_int(athlete.get("weight")),
        birth_date=date.fromisoformat(birth[:10]) if birth else None,
        college=(athlete.get("college") or {}).get("name"),
        experience_years=_clean_int((athlete.get("experience") or {}).get("years")),
        active=(athlete.get("status") or {}).get("type", "active") == "active",
    )


def parse_roster(raw: dict[str, Any]) -> list[RosterPlayer]:
    players: list[RosterPlayer] = []
    for athlete in _roster_athletes(raw):
        try:
            players.append(_roster_player(athlete))
        except (KeyError, ValueError, TypeError, ValidationError):
            continue
    return players


_PLAYER_ID_IN_URL = re.compile(r"/id/(\d+)")
_PLAYER_ID_IN_HEADSHOT = re.compile(r"/(\d+)\.png")


def _injury_player_id(athlete: dict[str, Any]) -> int | None:
    """The injuries feed has no athlete id field; it's only in the player URLs."""
    for link in athlete.get("links") or []:
        match = _PLAYER_ID_IN_URL.search(link.get("href", ""))
        if match:
            return int(match.group(1))
    match = _PLAYER_ID_IN_HEADSHOT.search((athlete.get("headshot") or {}).get("href", ""))
    return int(match.group(1)) if match else None


def _injury_note(status: str, short: str | None, long: str | None) -> str | None:
    """Prefer the short comment, but ESPN often puts only "questionable" there."""
    note = short if short and len(short) >= _MIN_USEFUL_NOTE_LENGTH else (long or short)
    if not note or note.strip().lower() == status.lower():
        return None
    return note.strip()


def parse_injuries(raw: dict[str, Any]) -> list[InjuryRecord]:
    try:
        team_entries = raw["injuries"]
    except (KeyError, TypeError) as exc:
        raise IngestionError("Unexpected ESPN injuries payload") from exc

    injuries: list[InjuryRecord] = []
    for team_entry in team_entries:
        for item in team_entry.get("injuries", []):
            status = item.get("status") or ""
            if not status or status == _HEALTHY_STATUS:
                continue
            player_id = _injury_player_id(item.get("athlete") or {})
            if player_id is None:
                continue
            reported = item.get("date")
            try:
                injuries.append(
                    InjuryRecord(
                        player_id=player_id,
                        status=status,
                        type=(item.get("details") or {}).get("type"),
                        note=_injury_note(
                            status, item.get("shortComment"), item.get("longComment")
                        ),
                        reported_at=_utc_naive(reported) if reported else None,
                    )
                )
            except (ValueError, ValidationError):
                continue
    return injuries


def parse_schedule(sport: str, raw: dict[str, Any]) -> list[ScheduledGame]:
    try:
        events = raw["events"]
    except (KeyError, TypeError) as exc:
        raise IngestionError("Unexpected ESPN schedule payload") from exc

    games: list[ScheduledGame] = []
    for event in events:
        try:
            competition = event["competitions"][0]
            competitors = competition["competitors"]
            home = next(c for c in competitors if c["homeAway"] == "home")
            away = next(c for c in competitors if c["homeAway"] == "away")
            games.append(
                ScheduledGame(
                    id=str(event["id"]),
                    season=season_label(sport, int(event["season"]["year"])),
                    start_time=_utc_naive(competition.get("date") or event["date"]),
                    status=status_state(event),
                    home_team_id=int(home["team"]["id"]),
                    away_team_id=int(away["team"]["id"]),
                    week=_clean_int((event.get("week") or {}).get("number")),
                    home_score=competitor_score(home),
                    away_score=competitor_score(away),
                )
            )
        except (
            KeyError,
            IndexError,
            StopIteration,
            TypeError,
            ValueError,
            ValidationError,
            IngestionError,
        ):
            continue
    return games


def parse_bye_week(raw: dict[str, Any]) -> int | None:
    """The team's bye week from its schedule payload (NFL only; the NBA has none)."""
    return _clean_int(raw.get("byeWeek"))


# ---------------------------------------------------------------------------
# Persistence: idempotent upserts keyed on ESPN ids.
# ---------------------------------------------------------------------------


def sync_teams(db: Session, sport: str, teams: list[TeamRecord]) -> dict[int, Team]:
    """Upsert teams, returning them keyed by ESPN team id."""
    existing = {
        team.external_id: team for team in db.scalars(select(Team).where(Team.sport == sport))
    }
    by_espn_id: dict[int, Team] = {}
    for record in teams:
        external_id = team_external_id(sport, record.id)
        team = existing.get(external_id)
        if team is None:
            team = Team(external_id=external_id, sport=sport)
            db.add(team)
        team.name = record.name
        team.abbreviation = record.abbreviation
        team.logo_url = record.logo_url
        team.primary_color = record.primary_color
        by_espn_id[record.id] = team
    db.flush()
    return by_espn_id


def sync_roster(
    db: Session,
    sport: str,
    team: Team,
    roster: list[RosterPlayer],
    players_by_external_id: dict[str, Player],
) -> None:
    """Upsert one team's roster; `players_by_external_id` is shared across the run."""
    for record in roster:
        player = players_by_external_id.get(str(record.id))
        if player is None:
            player = Player(external_id=str(record.id), sport=sport)
            db.add(player)
            players_by_external_id[str(record.id)] = player
        player.name = record.name
        player.team_id = team.id
        player.position = record.position
        player.jersey_number = record.jersey_number
        player.headshot_url = record.headshot_url
        player.height_inches = record.height_inches
        player.weight_lbs = record.weight_lbs
        player.birth_date = record.birth_date
        player.college = record.college
        player.experience_years = record.experience_years
        player.active = record.active
    db.flush()


def deactivate_unlisted(players_by_external_id: dict[str, Player], seen: set[str]) -> int:
    """Mark players missing from every roster inactive (their team is left as-is so
    old game logs still resolve an opponent)."""
    count = 0
    for external_id, player in players_by_external_id.items():
        if external_id not in seen and player.active:
            player.active = False
            count += 1
    return count


def sync_injuries(
    injuries: list[InjuryRecord], players_by_external_id: dict[str, Player]
) -> int:
    """Replace the current injury report: everyone is cleared, then the feed applied."""
    for player in players_by_external_id.values():
        player.injury_status = None
        player.injury_type = None
        player.injury_note = None
        player.injury_updated_at = None
    applied = 0
    for injury in injuries:
        player = players_by_external_id.get(str(injury.player_id))
        if player is None:
            continue
        player.injury_status = injury.status
        player.injury_type = injury.type
        player.injury_note = injury.note
        player.injury_updated_at = injury.reported_at
        applied += 1
    return applied


def sync_games(
    db: Session,
    sport: str,
    games: list[ScheduledGame],
    teams_by_espn_id: dict[int, Team],
    games_by_external_id: dict[str, Game],
) -> int:
    synced = 0
    for record in games:
        home = teams_by_espn_id.get(record.home_team_id)
        away = teams_by_espn_id.get(record.away_team_id)
        if home is None or away is None:
            continue
        game = games_by_external_id.get(record.id)
        if game is None:
            game = Game(external_id=record.id, sport=sport)
            db.add(game)
            games_by_external_id[record.id] = game
        game.season = record.season
        game.home_team_id = home.id
        game.away_team_id = away.id
        game.start_time = record.start_time
        game.status = record.status
        game.week = record.week
        game.home_score = record.home_score
        game.away_score = record.away_score
        synced += 1
    db.flush()
    return synced


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class SyncReport:
    sport: str
    teams: int = 0
    players: int = 0
    deactivated: int = 0
    injuries: int = 0
    games: int = 0
    failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        line = (
            f"{self.sport}: {self.teams} teams, {self.players} players "
            f"({self.deactivated} deactivated), {self.injuries} injuries, {self.games} games"
        )
        if self.failures:
            line += f"; {len(self.failures)} failed: {', '.join(self.failures)}"
        return line


def sync_sport(db: Session, client: ESPNClient, sport: str) -> SyncReport:
    """Sync one sport in the caller's session (the caller commits).

    One team's roster or schedule failing to load is recorded and skipped rather
    than aborting the run, but then nobody is deactivated — a missing roster would
    otherwise look like a whole team of players leaving the league.
    """
    espn_sport, espn_league = LEAGUES[sport]
    report = SyncReport(sport=sport)

    teams = sync_teams(db, sport, parse_teams(client.teams(espn_sport, espn_league)))
    report.teams = len(teams)

    players = {
        player.external_id: player
        for player in db.scalars(select(Player).where(Player.sport == sport))
        if player.external_id
    }
    games = {
        game.external_id: game
        for game in db.scalars(select(Game).where(Game.sport == sport))
        if game.external_id
    }
    seen_players: set[str] = set()
    seen_games: set[str] = set()

    for espn_id, team in teams.items():
        try:
            roster = parse_roster(client.roster(espn_sport, espn_league, str(espn_id)))
            sync_roster(db, sport, team, roster, players)
            seen_players.update(str(record.id) for record in roster)
        except (ESPNError, IngestionError):
            report.failures.append(f"{team.abbreviation} roster")
        try:
            raw_schedule = client.schedule(espn_sport, espn_league, str(espn_id))
            team.bye_week = parse_bye_week(raw_schedule)
            schedule = parse_schedule(sport, raw_schedule)
            fresh = [game for game in schedule if game.id not in seen_games]
            seen_games.update(game.id for game in fresh)
            report.games += sync_games(db, sport, fresh, teams, games)
        except (ESPNError, IngestionError):
            report.failures.append(f"{team.abbreviation} schedule")

    report.players = len(seen_players)
    if not any(failure.endswith("roster") for failure in report.failures):
        report.deactivated = deactivate_unlisted(players, seen_players)

    try:
        injuries = parse_injuries(client.injuries(espn_sport, espn_league))
        report.injuries = sync_injuries(injuries, players)
    except (ESPNError, IngestionError):
        report.failures.append("injuries")
    db.flush()
    return report


def run(sports: list[str]) -> list[SyncReport]:
    from app.db.session import SessionLocal

    settings = get_settings()
    reports: list[SyncReport] = []
    for sport in sports:
        timeout = (
            settings.nba_api_timeout_seconds if sport == "NBA" else settings.nfl_api_timeout_seconds
        )
        client = ESPNClient(timeout=timeout)
        db = SessionLocal()
        try:
            reports.append(sync_sport(db, client, sport))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            client.close()
            db.close()
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync teams, rosters, injuries and schedules from ESPN"
    )
    parser.add_argument("--sport", choices=["NBA", "NFL", "all"], default="all")
    args = parser.parse_args()
    sports = list(LEAGUES) if args.sport == "all" else [args.sport]
    for report in run(sports):
        print(report.summary())


if __name__ == "__main__":
    main()
