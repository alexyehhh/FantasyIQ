"""The scoreboard: every game in the current scoring period, whatever its status.

Unlike players.get_weekly_top_scorers (the best *finished* results), this is meant for a
live-ish scoreboard strip, so it includes games that haven't been played yet or are still
in progress alongside final ones.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import Game
from app.services.players import get_current_season
from app.services.projections.service import current_week
from app.services.projections.sleeper import et_date


def _current_nba_anchor(db: Session, now: datetime) -> datetime | None:
    """The start time of the NBA's next unfinished game, or its latest game once the schedule
    has run out. Mirrors current_week's "earliest unfinished, else latest" rule, but for a day
    of games rather than a week."""
    upcoming = db.scalar(
        select(Game.start_time)
        .where(
            Game.sport == "NBA",
            or_(
                and_(Game.status == "scheduled", Game.start_time >= now),
                Game.status == "in_progress",
            ),
        )
        .order_by(Game.start_time)
        .limit(1)
    )
    if upcoming is not None:
        return upcoming
    return db.scalar(
        select(Game.start_time).where(Game.sport == "NBA").order_by(Game.start_time.desc()).limit(1)
    )


def get_scoreboard(
    db: Session, *, sport: str, week: int | None = None, now: datetime | None = None
) -> tuple[int | None, list[Game]]:
    """Every game in the current scoring period: an NFL week (given, or the current one), or
    for the NBA the (US Eastern) date of its next games. Returns (week, games) in kickoff
    order; week is always None for the NBA. Empty once a sport's season hasn't started."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    season = get_current_season(db, sport, now=now)
    if season is None:
        return None, []

    if sport == "NFL":
        week = week or current_week(db, sport, now=now)
        if week is None:
            return None, []
        games = db.scalars(
            select(Game)
            .where(Game.sport == sport, Game.season == season, Game.week == week)
            .order_by(Game.start_time)
        ).all()
        return week, list(games)

    anchor = _current_nba_anchor(db, now)
    if anchor is None:
        return None, []
    day = et_date(anchor)
    # A US Eastern day spans 24h of naive-UTC start times; a day either side of the anchor
    # always covers it, and the et_date check in Python picks out exactly that day's games.
    candidates = db.scalars(
        select(Game).where(
            Game.sport == sport,
            Game.season == season,
            Game.start_time >= anchor - timedelta(hours=24),
            Game.start_time <= anchor + timedelta(hours=24),
        )
    )
    games = sorted(
        (g for g in candidates if et_date(g.start_time) == day), key=lambda g: g.start_time
    )
    return None, games
