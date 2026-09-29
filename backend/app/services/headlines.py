"""Home page headlines: standout performances and real injury news for fantasy-relevant
players, built entirely from data already synced from ESPN.

Nothing here is generated or guessed — a performance headline is a template filled in from
a finished game's real stat line, and an injury headline is ESPN's own reported note (a
player is skipped rather than reduced to a bare designation when there's no real note on
file). Both are limited to offensive skill positions with a real season role, so a
lineman's ankle sprain or a one-catch afterthought's injury doesn't crowd out real fantasy
news.
"""

from dataclasses import dataclass
from datetime import datetime
from itertools import zip_longest

from sqlalchemy.orm import Session

from app.db.models import Player, Team
from app.services import players as players_service
from app.services.players import TopScorer
from app.services.scoring import ScoringConfig

# The offensive skill positions fantasy football is actually played at; a lineman's or
# defensive back's injury isn't fantasy news, and neither (for headline purposes) is a
# kicker's. The NBA has no such split, so nothing is filtered there.
NFL_SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# A note this short is just ESPN's designation restated ("ir", "inactive"), not real reporting;
# without a real note, a player is left out rather than reduced to a bare "is Out" sentence.
_MIN_NOTE_LENGTH = 25

# A player below this many season fantasy points hasn't shown a real role yet — the one-catch,
# then-injured afterthought the news feed shouldn't bother with, however it happened.
_MIN_SEASON_POINTS = 10.0


@dataclass
class Headline:
    kind: str  # "injury" | "performance"
    player: Player
    text: str
    at: datetime


def _mascot(team_name: str) -> str:
    """A team's name without its city, the way a ticker headline would say it ("Cardinals")."""
    return team_name.rsplit(" ", 1)[-1]


def _game_phrase(result: str | None, is_home: bool | None, opponent: Team | None) -> str:
    if opponent is None or result is None:
        return ""
    where = "vs" if is_home else "at"
    outcome = {"W": "win", "L": "loss", "T": "tie"}.get(result, "game")
    return f"in a {outcome} {where} {_mascot(opponent.name)}"


def _plural(count: float) -> str:
    return "" if count == 1 else "s"


def _performance_text(scorer: TopScorer) -> str | None:
    """A one-line recap of a real stat line, or None for a position with no good template
    (rare among top scorers — mostly defenses, which never appear here)."""
    stats = players_service.serialize_stats_row(scorer.stats_row)
    name = scorer.player.name
    phrase = _game_phrase(scorer.result, scorer.is_home, scorer.opponent)

    if scorer.player.sport == "NBA":
        points = stats.get("points", 0)
        rebounds, assists = stats.get("rebounds", 0), stats.get("assists", 0)
        return (
            f"{name} scored {points:g} points with {rebounds:g} rebounds and "
            f"{assists:g} assists {phrase}."
        ).strip()

    position = scorer.player.position
    if position == "QB":
        yards, td = stats.get("passing_yards", 0), stats.get("passing_touchdowns", 0)
        return f"{name} threw for {yards:g} yards and {td:g} TD{_plural(td)} {phrase}.".strip()
    if position in ("RB", "FB"):
        yards, td = stats.get("rushing_yards", 0), stats.get("rushing_touchdowns", 0)
        receptions, rec_yards = stats.get("receptions", 0), stats.get("receiving_yards", 0)
        text = f"{name} rushed for {yards:g} yards and {td:g} TD{_plural(td)}"
        if receptions >= 3:
            text += f", adding {receptions:g} catches for {rec_yards:g} yards,"
        return f"{text} {phrase}.".strip()
    if position in ("WR", "TE"):
        receptions = stats.get("receptions", 0)
        yards, td = stats.get("receiving_yards", 0), stats.get("receiving_touchdowns", 0)
        return (
            f"{name} caught {receptions:g} passes for {yards:g} yards and {td:g} "
            f"TD{_plural(td)} {phrase}."
        ).strip()
    return None  # kickers, defenses, and other non-skill positions get no headline


def _performance_headlines(
    db: Session, *, sport: str, config: ScoringConfig | None, pool: int
) -> list[Headline]:
    scorers, _week = players_service.get_weekly_top_scorers(
        db, sport=sport, scoring=config, limit=pool
    )
    headlines = []
    for scorer in scorers:
        text = _performance_text(scorer)
        if text is None:
            continue
        headlines.append(
            Headline(
                kind="performance", player=scorer.player, text=text, at=scorer.game.start_time
            )
        )
    return headlines


def _injury_text(player: Player) -> str | None:
    """The real reported note, or None when there isn't one worth a headline (see
    _MIN_NOTE_LENGTH) — a player without real reporting is left out, not stubbed in."""
    note = (player.injury_note or "").strip()
    return note if len(note) >= _MIN_NOTE_LENGTH else None


def _injury_headlines(
    db: Session, *, sport: str, scoring: ScoringConfig | None, pool: int
) -> list[Headline]:
    positions = NFL_SKILL_POSITIONS if sport == "NFL" else None
    candidates = players_service.get_injury_report(db, sport=sport, positions=positions, limit=pool)
    season_points = players_service.get_season_fantasy_points(db, candidates, scoring=scoring)

    headlines = []
    for player in candidates:
        if player.injury_updated_at is None:
            continue
        if season_points.get(player.id, 0.0) < _MIN_SEASON_POINTS:
            continue
        text = _injury_text(player)
        if text is None:
            continue
        headlines.append(
            Headline(kind="injury", player=player, text=text, at=player.injury_updated_at)
        )
    return headlines


def get_headlines(
    db: Session, *, sport: str, scoring: ScoringConfig | None = None, limit: int = 12
) -> list[Headline]:
    """Standout performances and real injury news for fantasy-relevant players.

    A pure time sort would let a busy injury-report day bury every performance (updates land
    all at once; a week's games are long since final), so the two are instead alternated —
    best performance, most recent injury, next-best performance, and so on — each keeping its
    own relevance order, until `limit` is reached or both run out. Each pulls a wider pool
    than `limit` up front, since the position, role, and real-reporting filters can turn away
    most candidates on a quiet day."""
    performances = _performance_headlines(db, sport=sport, config=scoring, pool=max(limit * 2, 20))
    injuries = _injury_headlines(db, sport=sport, scoring=scoring, pool=max(limit * 8, 100))

    combined: list[Headline] = []
    for performance, injury in zip_longest(performances, injuries):
        for headline in (performance, injury):
            if headline is not None:
                combined.append(headline)
    return combined[:limit]
