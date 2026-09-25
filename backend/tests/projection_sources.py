"""A projection source for tests that returns whatever stat lines it is given.

The service tests are about scoring, choosing the game, ranking and flagging, not about where the
numbers come from, so they use this instead of a real source."""

from sqlalchemy import select

from app.db.models import Player, Team
from app.services.projections import base
from app.services.projections.base import KickBucket, RankedCandidate, StatProjection, Unavailable
from app.services.projections.expected_scoring import score_expected_defense, score_expected_player


class StaticSource:
    name = "static"
    label = "Static"
    description = "Test source"
    sports = frozenset({"NBA", "NFL"})

    def __init__(self, lines: dict[str, dict[str, float] | Unavailable], kicks=None):
        self.lines = lines
        self.kicks: dict[str, list[KickBucket]] = kicks or {}
        self.asked: list[str] = []

    def project(self, db, targets, config):
        answers = {}
        for target in targets:
            self.asked.append(target.name)
            line = self.lines.get(target.name)
            if line is None:
                answers[target.key] = Unavailable("Not in the static source")
            elif isinstance(line, Unavailable):
                answers[target.key] = line
            else:
                answers[target.key] = StatProjection(
                    stats=dict(line), kicks=self.kicks.get(target.name, [])
                )
        return answers

    def rank(self, db, *, sport, season, week, day, positions, defenses, config):
        self.ranked_for = (sport, week, day, positions, defenses)
        ranked = []
        for name, line in self.lines.items():
            if isinstance(line, Unavailable):
                continue
            if defenses:
                team = db.scalar(
                    select(Team).where(Team.sport == sport, Team.name + " D/ST" == name)
                )
                if team:
                    points = score_expected_defense(config, line).points
                    ranked.append(RankedCandidate("defense", team.id, points))
                continue
            player = db.scalar(select(Player).where(Player.sport == sport, Player.name == name))
            if player and (not positions or player.position in positions):
                points = score_expected_player(config, line, self.kicks.get(name, [])).points
                ranked.append(RankedCandidate("player", player.id, points, player.injury_status))
        return sorted(ranked, key=lambda c: -c.points)


def install(monkeypatch, lines, kicks=None) -> StaticSource:
    """Registers a static source under the name "static" for the length of the test."""
    source = StaticSource(lines, kicks)
    monkeypatch.setitem(base.PROVIDERS, "static", source)
    return source
