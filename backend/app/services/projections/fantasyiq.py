"""The `fantasyiq` source: our own model, trained on the games in our database (`app/ml`).

It answers the same question as Sleeper, in raw stats, so it is rescored with the caller's
`ScoringConfig` like every source. What it knows is a player's own recent games, home or away and
rest, so unlike Sleeper it is not matchup-aware yet for players. It covers NBA players, NFL
QB/RB/WR/TE and NFL team defenses (`fantasyiq_defense`, which does allow for the opponent's
offense) and NFL kickers (`fantasyiq_kicker`: expected attempts by distance, and the kicker's
own make rates); anyone with fewer than a few games of history is unavailable.

Nothing is stored: a projection is computed on request from the saved model file (`models/`,
written by `python -m app.ml.train`) and the finished games already in the database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Game, Player
from app.ml import defense as defense_model
from app.ml import model as ml_model
from app.ml.availability import EXPECTED_OUT, Timeline
from app.ml.dataset import POSITION_ALIASES, POSITIONS, STATS, load_history, load_team_games
from app.ml.features import MIN_PRIOR_GAMES, POSITION_CODES, build_features
from app.services.projections import fantasyiq_defense, fantasyiq_kicker
from app.services.projections.base import (
    Key,
    ProjectionError,
    RankedCandidate,
    StatProjection,
    Target,
    Unavailable,
    register,
)
from app.services.projections.expected_scoring import (
    score_expected_defense,
    score_expected_player,
)
from app.services.projections.fantasyiq_defense import DefenseRow
from app.services.projections.fantasyiq_kicker import KICKER_POSITIONS, KickerRow, is_kicker
from app.services.projections.news import TeamNews, team_news
from app.services.projections.sleeper import et_date
from app.services.scoring import ScoringConfig, player_stat_values

# Stats a league may score that the model doesn't project but that almost never happen.
_RARE_STATS = {"kick_return_touchdowns", "punt_return_touchdowns"}
_NOT_MODELLED = "The FantasyIQ model doesn't project {what} yet"


@dataclass(frozen=True)
class _Row:
    """One player's game to project."""

    player: Player
    game: Game
    is_home: bool


# Per sport: (how many finished games there were, the latest one) -> all history and who played
# with whom. Rebuilt only when a game has finished since, because every projection reads it.
_data_cache: dict[str, tuple[tuple[int, object], pd.DataFrame, Timeline]] = {}


def _data(db: Session, sport: str) -> tuple[pd.DataFrame, Timeline]:
    key = db.execute(
        select(func.count(Game.id), func.max(Game.start_time)).where(
            Game.sport == sport, Game.status == "final", Game.stats_final.is_(True)
        )
    ).one()
    cached = _data_cache.get(sport)
    if cached is None or cached[0] != tuple(key):
        history = load_history(db.connection(), sport)
        timeline = Timeline(history, load_team_games(db.connection(), sport), STATS[sport])
        cached = (tuple(key), history, timeline)
        _data_cache[sport] = cached
    return cached[1], cached[2]


def _position(player: Player) -> str | None:
    position = POSITION_ALIASES.get(player.position or "", player.position)
    return position if position in POSITION_CODES else None


class FantasyIQProvider:
    name = "fantasyiq"
    label = "FantasyIQ model"
    description = (
        "Our own gradient boosting model, trained on two seasons of NBA and NFL box scores. It "
        "projects from a player's recent games, home or away, rest and which teammates are out "
        "(a backup's workload rises when the starter is hurt); it does not use the opponent for "
        "players yet. NBA players and NFL QB, RB, WR and TE, plus NFL team defenses (which do "
        "allow for the opponent's offense) and kickers (expected kicks by distance from the "
        "team's scoring and the opponent's defense, with the kicker's own make rates)."
    )
    sports = frozenset({"NBA", "NFL"})

    def _predict(
        self, db: Session, sport: str, rows: Sequence[_Row]
    ) -> dict[int, StatProjection | Unavailable]:
        """Stat lines by player id. A player without enough history is Unavailable."""
        saved = ml_model.load_cached(sport)
        if saved is None:
            raise ProjectionError(
                f"The FantasyIQ {sport} model hasn't been trained (python -m app.ml.train)"
            )
        stats = STATS[sport]
        results: dict[int, StatProjection | Unavailable] = {}
        eligible: list[_Row] = []
        for row in rows:
            position = _position(row.player)
            if position is None or position not in _covered(sport, POSITIONS[sport]):
                what = f"{row.player.position or 'unknown-position'} players"
                results[row.player.id] = Unavailable(_NOT_MODELLED.format(what=what))
            else:
                eligible.append(row)
        if not eligible:
            return results

        everyone, timeline = _data(db, sport)
        ids = {r.player.id for r in eligible}
        history = everyone[everyone["player_id"].isin(ids)]
        starts = {r.player.id: r.game.start_time for r in eligible}
        # Only games before the one being projected, so a game already played is projected as it
        # would have been beforehand.
        history = history[history["start_time"] < history["player_id"].map(starts)]
        teams = {r.player.team_id for r in eligible}
        news = team_news(db, sport, teams)
        out = _expected_out(db, teams)
        for team_id, ids in news.out_by_team.items():
            out.setdefault(team_id, set()).update(ids)
        targets = pd.DataFrame(
            [
                {
                    "player_id": r.player.id,
                    "start_time": pd.Timestamp(r.game.start_time),
                    "position": _position(r.player),
                    "is_home": float(r.is_home),
                    **timeline.features_for(
                        r.player.id,
                        r.player.team_id,
                        r.game.season,
                        timeline.position_before(r.player.team_id, pd.Timestamp(r.game.start_time)),
                        out.get(r.player.team_id, set()),
                        news.depth,
                    ),
                }
                for r in eligible
            ]
        )
        news_notes, news_facts = _news_notes(db, timeline, eligible, out, news)
        stacked = pd.concat([history, targets], ignore_index=True)
        stacked = stacked.sort_values(["player_id", "start_time"]).reset_index(drop=True)
        features = build_features(stacked, stats)
        projected = features[features["start_time"] == features["player_id"].map(starts)]
        projected = projected[projected[stats[0]].isna()]  # the appended target rows
        lines = saved.predict(projected)
        for index, player_id in projected["player_id"].items():
            if projected.loc[index, "n_prior"] < MIN_PRIOR_GAMES:
                results[int(player_id)] = Unavailable(
                    f"Fewer than {MIN_PRIOR_GAMES} games of history for the model to go on"
                )
                continue
            results[int(player_id)] = StatProjection(
                stats={stat: float(v) for stat, v in lines.loc[index].items()},
                notes=[
                    f"Projection from the FantasyIQ model (games to {saved.trained_through}).",
                    *news_notes.get(int(player_id), []),
                ],
                meta={
                    "trained_through": saved.trained_through,
                    "first_choice_share": get_settings().projection_first_choice_share,
                    **news_facts.get(int(player_id), {}),
                },
            )
        return results

    def project(
        self, db: Session, targets: Sequence[Target], config: ScoringConfig
    ) -> dict[Key, StatProjection | Unavailable]:
        sport = targets[0].sport if targets else ""
        results: dict[Key, StatProjection | Unavailable] = {}
        rows = []
        defenses = [t for t in targets if t.kind == "defense"]
        if defenses:
            missing_defense = sorted(
                {s for s, w in config.defense_weights.items() if w}
                - set(defense_model.STATS)
                - {"yards_allowed"}
            )
            answers = fantasyiq_defense.predict(
                db, [DefenseRow(t.entity_id, t.game) for t in defenses]
            )
            for target in defenses:
                answer = answers.get(
                    target.entity_id, Unavailable("No projection for this defense")
                )
                if isinstance(answer, StatProjection):
                    answer.unprojected = missing_defense
                results[target.key] = answer
        kickers = []
        for target in targets:
            if target.kind == "defense":
                continue
            if target.sport == "NFL" and is_kicker(target.player):
                assert target.player is not None
                kickers.append(KickerRow(target.player, target.game))
            elif target.player is None:
                results[target.key] = Unavailable(_NOT_MODELLED.format(what="this"))
            else:
                rows.append(_Row(target.player, target.game, target.is_home))
        supported = set(STATS.get(sport, ())) | set(player_stat_values(config.sport, {}))
        weighted = {s for s, w in config.player_weights.items() if w}
        missing = sorted(weighted - supported - _RARE_STATS)
        if kickers:
            missing_kicks = sorted(set(missing) - fantasyiq_kicker.KICKER_STATS)
            by_kicker = fantasyiq_kicker.predict(db, kickers)
            for target in targets:
                answer = by_kicker.get(target.entity_id)
                if target.kind == "player" and is_kicker(target.player) and answer is not None:
                    if isinstance(answer, StatProjection):
                        answer.unprojected = missing_kicks
                    results[target.key] = answer
        if rows:
            by_player = self._predict(db, sport, rows)
            for target in targets:
                answer = by_player.get(target.entity_id)
                if target.kind == "player" and answer is not None:
                    if isinstance(answer, StatProjection):
                        answer.unprojected = missing
                    results[target.key] = answer
        return results

    def _rank_defenses(
        self, db: Session, season: str, week: int | None, config: ScoringConfig
    ) -> list[RankedCandidate]:
        """Every NFL defense playing in `week`, best expected fantasy points first."""
        if week is None:
            return []
        games = db.scalars(
            select(Game).where(Game.sport == "NFL", Game.season == season, Game.week == week)
        )
        rows = [DefenseRow(team, g) for g in games for team in (g.home_team_id, g.away_team_id)]
        ranked = [
            RankedCandidate("defense", team_id, score_expected_defense(config, answer.stats).points)
            for team_id, answer in fantasyiq_defense.predict(db, rows).items()
            if isinstance(answer, StatProjection)
        ]
        return sorted(ranked, key=lambda c: -c.points)

    def rank(
        self,
        db: Session,
        *,
        sport: str,
        season: str,
        week: int | None,
        day: date | None,
        positions: Sequence[str] | None,
        defenses: bool,
        config: ScoringConfig,
    ) -> list[RankedCandidate]:
        if defenses:
            return self._rank_defenses(db, season, week, config) if sport == "NFL" else []
        query = select(Game).where(Game.sport == sport, Game.season == season)
        if sport == "NFL":
            if week is None:
                return []
            games = list(db.scalars(query.where(Game.week == week)))
        else:
            if day is None:
                return []
            start = datetime.combine(day, time.min)
            nearby = query.where(
                Game.start_time >= start - timedelta(days=1),
                Game.start_time <= start + timedelta(days=2),
            )
            games = [g for g in db.scalars(nearby) if et_date(g.start_time) == day]
        by_team = {}
        for game in games:
            by_team[game.home_team_id] = (game, True)
            by_team[game.away_team_id] = (game, False)
        if not by_team:
            return []
        covered = _covered(sport, positions or POSITIONS[sport])
        players = db.scalars(
            select(Player).where(
                Player.sport == sport, Player.active.is_(True), Player.team_id.in_(by_team)
            )
        ).all()
        rows = [
            _Row(p, *by_team[p.team_id])
            for p in players
            if p.team_id is not None and (_position(p) in covered)
        ]
        injuries = {r.player.id: r.player.injury_status for r in rows}
        ranked = []
        for player_id, answer in self._predict(db, sport, rows).items():
            if isinstance(answer, StatProjection):
                points = score_expected_player(config, answer.stats).points
                ranked.append(RankedCandidate("player", player_id, points, injuries[player_id]))
        if sport == "NFL" and (positions is None or KICKER_POSITIONS & set(positions)):
            kickers = [
                KickerRow(p, by_team[p.team_id][0])
                for p in players
                if p.team_id is not None and is_kicker(p)
            ]
            for player_id, answer in fantasyiq_kicker.predict(db, kickers).items():
                if isinstance(answer, StatProjection):
                    points = score_expected_player(config, answer.stats, answer.kicks).points
                    kicker = next(k.player for k in kickers if k.player.id == player_id)
                    ranked.append(
                        RankedCandidate("player", player_id, points, kicker.injury_status)
                    )
        return sorted(ranked, key=lambda c: -c.points)


def _news_notes(
    db: Session, timeline: Timeline, rows: Sequence[_Row], out: dict[int, set[int]], news: TeamNews
) -> tuple[dict[int, list[str]], dict[int, dict[str, object]]]:
    """What news moved each projection, in words (which teammates are out, where the depth chart
    puts the player) and as data to save with a snapshot."""
    missing: dict[int, set[int]] = {}
    for row in rows:
        team = row.player.team_id
        k = timeline.position_before(team, pd.Timestamp(row.game.start_time))
        _, gone, _, _ = timeline.context(team, row.game.season, k, out.get(team, set()))
        missing[row.player.id] = gone - {row.player.id}
    ids = set().union(*missing.values()) if missing else set()
    people = {p.id: p for p in db.scalars(select(Player).where(Player.id.in_(ids)))} if ids else {}
    notes: dict[int, list[str]] = {}
    facts: dict[int, dict[str, object]] = {}
    for row in rows:
        lines = []
        names = [
            f"{people[q].name} ({news.notes.get(q) or people[q].injury_status or 'out'})"
            for q in sorted(missing[row.player.id])
            if q in people
        ]
        if names:
            lines.append(f"Teammates out, so the workload is adjusted: {', '.join(names)}.")
        order = news.depth.get(row.player.id)
        if order is not None:
            lines.append(f"Depth chart lists him {row.player.position}{order}.")
        read = news.read.get(row.player.id)
        if read and read.get("note"):
            lines.append(f"News: {read['note']}")
        notes[row.player.id] = lines
        facts[row.player.id] = {
            "teammates_out": [
                people[q].name for q in sorted(missing[row.player.id]) if q in people
            ],
            "depth_order": order,
            "news": news.read.get(row.player.id),
        }
    return notes, facts


def _expected_out(db: Session, team_ids: set[int | None]) -> dict[int, set[int]]:
    """Each team's players currently listed out, doubtful or suspended."""
    rows = db.execute(
        select(Player.team_id, Player.id).where(
            Player.team_id.in_([t for t in team_ids if t is not None]),
            func.lower(Player.injury_status).in_(EXPECTED_OUT),
        )
    )
    out: dict[int, set[int]] = {}
    for team_id, player_id in rows:
        out.setdefault(team_id, set()).add(player_id)
    return out


def _covered(sport: str, wanted: Sequence[str]) -> set[str]:
    """The model's positions among `wanted` (ESPN codes), a fullback counting as a running back."""
    return {POSITION_ALIASES.get(p, p) for p in wanted} & set(POSITION_CODES)


FANTASYIQ = register(FantasyIQProvider())
