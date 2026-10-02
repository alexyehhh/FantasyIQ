"""The kicker model's data loading, features, make rates and projections (real Postgres for the
loader and the source, rolled back after)."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.db.models import (
    FieldGoalKick,
    Game,
    Player,
    PlayerGameStatsNFL,
    Team,
    TeamGameStatsNFL,
)
from app.db.session import SessionLocal
from app.ml import kicker
from app.services.projections import base, fantasyiq, fantasyiq_kicker
from app.services.scoring import default_config

NFL = default_config("NFL")


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _history(games: int = 8) -> pd.DataFrame:
    """Teams 1 and 2 play each other weekly. Team 1 scores 30 and kicks 4 extra points and one
    field goal from 30-39; team 2 scores 10 and kicks 1 extra point and 3 field goals."""
    rows = []
    for week in range(1, games + 1):
        start = pd.Timestamp("2026-09-01") + pd.Timedelta(days=7 * week)
        for team, opponent, home, xpa, fg, scored, allowed in (
            (1, 2, 1, 4.0, 1.0, 30, 10),
            (2, 1, 0, 1.0, 3.0, 10, 30),
        ):
            row = {
                "team_id": team, "opponent_id": opponent, "game_id": week, "start_time": start,
                "season": "2026", "week": float(week), "is_home": home,
                "points_scored": float(scored), "points_allowed": float(allowed),
                "xpa": xpa, "fga": fg,
            }  # fmt: skip
            row.update({f"fga_{b}": 0.0 for b in kicker.BUCKETS})
            row["fga_30_39"] = fg
            rows.append(row)
    return pd.DataFrame(rows).sort_values(["team_id", "start_time"]).reset_index(drop=True)


def test_a_distance_goes_into_its_range():
    assert [kicker.bucket_of(d) for d in (18, 19, 20, 29, 30, 49, 50, 64, 70)] == [
        "0_19", "0_19", "20_29", "20_29", "30_39", "40_49", "50p", "50p", "50p",
    ]  # fmt: skip


def test_features_use_only_earlier_games():
    frame = _history()
    base_features = kicker.build_features(frame)
    changed = frame.copy()
    later = (changed["team_id"] == 1) & (changed["game_id"] >= 5)
    changed.loc[later, ["xpa", "fga", "fga_30_39", "points_scored"]] += 1000
    altered = kicker.build_features(changed)

    columns = [c for c in base_features.columns if "__" in c]
    early = base_features["game_id"] <= 5  # game 5's own features see games 1-4 only
    pd.testing.assert_frame_equal(base_features.loc[early, columns], altered.loc[early, columns])
    assert not base_features.loc[base_features["game_id"] == 6, columns].equals(
        altered.loc[altered["game_id"] == 6, columns]
    )


def test_the_opponents_defense_comes_from_what_it_has_allowed():
    features = kicker.build_features(_history())

    team_1 = features[(features["team_id"] == 1) & (features["game_id"] == 5)].iloc[0]
    team_2 = features[(features["team_id"] == 2) & (features["game_id"] == 5)].iloc[0]

    assert team_1["opp_points_allowed__ewm"] == pytest.approx(30)  # team 2 allows 30 a game
    assert team_2["opp_points_allowed__ewm"] == pytest.approx(10)
    assert team_1["own_points_scored__ewm"] == pytest.approx(30)


def test_a_game_with_no_kicks_is_left_out_of_the_averages_not_counted_as_zeros():
    frame = _history()
    quiet = (frame["team_id"] == 1) & (frame["game_id"] == 3)
    frame.loc[quiet, [*kicker.ATTEMPTS, "fga"]] = np.nan

    features = kicker.build_features(frame)
    after = features[(features["team_id"] == 1) & (features["game_id"] == 4)].iloc[0]

    assert after["xpa__ewm"] == pytest.approx(4)


def test_a_kickers_rate_is_his_record_blended_with_the_leagues():
    league = kicker.LeagueRates({b: 0.8 for b in kicker.BUCKETS}, 0.95)
    nothing = pd.DataFrame([{**{f"att_{b}": 0 for b in kicker.BUCKETS}, "xpa": 0, "xpm": 0}])
    nothing = nothing.assign(**{f"made_{b}": 0 for b in kicker.BUCKETS})
    assert kicker.kicker_rates(nothing, league).field_goal["40_49"] == pytest.approx(0.8)

    # 20 makes in 20 from 40-49 against a league 0.8 that counts as 20 kicks: halfway to 1.
    perfect = nothing.assign(att_40_49=20, made_40_49=20)
    assert kicker.kicker_rates(perfect, league).field_goal["40_49"] == pytest.approx(0.9)
    assert kicker.kicker_rates(perfect, league).field_goal["50p"] == pytest.approx(0.8)


def test_the_expected_line_splits_attempts_into_makes_and_misses_by_distance():
    league = kicker.LeagueRates({b: 0.5 for b in kicker.BUCKETS}, 0.9)
    attempts = {"xpa": 3.0, **{f"fga_{b}": 0.0 for b in kicker.BUCKETS}, "fga_40_49": 2.0}

    stats, kicks = kicker.expected_line(attempts, league)

    assert stats == pytest.approx(
        {
            "field_goal_attempts": 2.0,
            "field_goals_made": 1.0,
            "extra_point_attempts": 3.0,
            "extra_points_made": 2.7,
        }
    )
    forties = next(k for k in kicks if k.low == 40)
    assert (forties.made, forties.missed) == (1.0, 1.0)


def test_the_model_predicts_non_negative_attempts_and_survives_a_save(tmp_path):
    rng = np.random.default_rng(1)
    frame = pd.concat([_history(10).assign(team_id=t, opponent_id=t % 4 + 1) for t in range(1, 5)])
    features = kicker.build_features(frame.sort_values(["team_id", "start_time"]).reset_index())
    ready = features[kicker.usable(features)].copy()
    for stat in kicker.ATTEMPTS:
        ready[stat] = rng.poisson(2, len(ready)).astype(float)
    league = kicker.LeagueRates({b: 0.8 for b in kicker.BUCKETS}, 0.95)

    model = kicker.KickerModel(kicker.train(ready), league, "2026-10-01", len(ready))
    predicted = model.predict(ready)

    assert list(predicted.columns) == list(kicker.ATTEMPTS)
    assert (predicted >= 0).all().all()
    kicker.save(model, tmp_path)
    reloaded = kicker.load_cached(tmp_path)
    assert reloaded is not None
    pd.testing.assert_frame_equal(reloaded.predict(ready), predicted)
    assert kicker.load_cached(tmp_path / "nowhere") is None


# --- Loading and the source, against the database ----------------------------------------------


def _team(db, name, abbreviation):
    team = Team(name=name, abbreviation=abbreviation, sport="NFL")
    db.add(team)
    db.flush()
    return team


def _final_game(db, home, away, week, days_ago):
    start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago)
    game = Game(
        sport="NFL", season="2026", home_team_id=home.id, away_team_id=away.id,
        start_time=start, week=week, status="final", stats_final=True,
    )  # fmt: skip
    db.add(game)
    db.flush()
    db.add_all(
        [
            TeamGameStatsNFL(team_id=home.id, game_id=game.id, points_allowed=17),
            TeamGameStatsNFL(team_id=away.id, game_id=game.id, points_allowed=20),
        ]
    )
    return game


def _kicker(db, team, name, position="PK"):
    player = Player(name=name, sport="NFL", team_id=team.id, position=position, active=True)
    db.add(player)
    db.flush()
    return player


def _kick(db, player, game, distance, result, n):
    db.add(
        FieldGoalKick(
            player_id=player.id, game_id=game.id, distance=distance, result=result,
            external_play_id=f"{game.id}-{player.id}-{n}",
        )
    )  # fmt: skip


@pytest.fixture
def league(db):
    """Four finished games between two teams; each team's kicker makes a 35-yarder and a 45-yarder
    miss every game and kicks two extra points."""
    alpha, bravo = _team(db, "Alpha Aces", "ALP"), _team(db, "Bravo Bears", "BRV")
    ann, bo = _kicker(db, alpha, "Ann Kicker"), _kicker(db, bravo, "Bo Booter")
    games = [_final_game(db, alpha, bravo, week, 40 - 7 * week) for week in range(1, 5)]
    for game in games:
        for player in (ann, bo):
            db.add(
                PlayerGameStatsNFL(
                    player_id=player.id, game_id=game.id, field_goal_attempts=2,
                    field_goals_made=1, extra_point_attempts=2, extra_points_made=2,
                )
            )  # fmt: skip
            _kick(db, player, game, 35, "made", 1)
            _kick(db, player, game, 45, "missed", 2)
    db.flush()
    return alpha, bravo, ann, bo, games


def test_the_loader_gives_each_team_its_kicking_and_each_kicker_his_ranges(db, league):
    alpha, _, ann, _, games = league

    history = kicker.load_history(db.connection())

    team_games = history.team_games
    row = team_games[(team_games["team_id"] == alpha.id) & (team_games["game_id"] == games[0].id)]
    assert row.iloc[0]["xpa"] == 2 and row.iloc[0]["fga_30_39"] == 1
    assert row.iloc[0]["fga_40_49"] == 1 and row.iloc[0]["points_scored"] == 20
    ann_games = history.kicker_games[history.kicker_games["player_id"] == ann.id]
    assert len(ann_games) == 4
    assert ann_games.iloc[0]["att_40_49"] == 1 and ann_games.iloc[0]["made_40_49"] == 0
    assert ann_games.iloc[0]["made_30_39"] == 1 and ann_games.iloc[0]["xpm"] == 2


def test_a_kicker_who_has_changed_teams_is_credited_to_the_team_he_kicked_for(db, league):
    alpha, bravo, ann, bo, games = league
    game = _final_game(db, alpha, bravo, 5, 1)
    for player in (ann, bo):
        db.add(PlayerGameStatsNFL(player_id=player.id, game_id=game.id, extra_point_attempts=3))
    ann.team_id = (
        None  # no longer on any team: Bravo's kicker is clear, so Alpha's is by elimination
    )
    db.flush()

    history = kicker.load_history(db.connection())

    new = history.kicker_games[history.kicker_games["game_id"] == game.id]
    assert dict(zip(new["player_id"], new["team_id"], strict=True)) == {
        ann.id: alpha.id,
        bo.id: bravo.id,
    }


class SteadyKicking:
    """Expects two extra points and one field goal from 30-39 and one from 40-49."""

    trained_through = "2026-01-01"
    league = kicker.LeagueRates({b: 0.8 for b in kicker.BUCKETS}, 0.95)

    def predict(self, features):
        out = {s: 0.0 for s in kicker.ATTEMPTS}
        out.update({"xpa": 2.0, "fga_30_39": 1.0, "fga_40_49": 1.0})
        return pd.DataFrame(out, index=features.index)


@pytest.fixture
def upcoming(db, league):
    alpha, bravo, ann, bo, _ = league
    start = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
    game = Game(
        sport="NFL", season="2026", home_team_id=alpha.id, away_team_id=bravo.id,
        start_time=start, week=6, status="scheduled", stats_final=False,
    )  # fmt: skip
    db.add(game)
    db.flush()
    fantasyiq_kicker._cache.clear()  # each test has its own games, which the cache can't tell apart
    return alpha, ann, game


def _project(db, kickers, game):
    opponent = db.get(Team, game.away_team_id)
    targets = [
        base.Target(
            "player", "NFL", p.id, p.name, None, p.position, game,
            opponent, game.home_team_id == p.team_id, p,
        )
        for p in kickers
    ]  # fmt: skip
    return fantasyiq.FANTASYIQ.project(db, targets, NFL)


def test_a_kicker_is_projected_from_his_teams_kicking_and_his_own_make_rate(
    db, upcoming, monkeypatch
):
    monkeypatch.setattr(fantasyiq_kicker.model, "load_cached", lambda *args: SteadyKicking())
    _, ann, game = upcoming

    answer = _project(db, [ann], game)[("player", ann.id)]

    assert isinstance(answer, base.StatProjection)
    assert answer.stats["extra_point_attempts"] == 2.0
    assert answer.stats["field_goal_attempts"] == 2.0
    thirties = next(k for k in answer.kicks if k.low == 30)
    forties = next(k for k in answer.kicks if k.low == 40)
    # Four made in four from 30-39 (blended up from the league's 0.8); none in four from 40-49.
    assert thirties.made > 0.8 and forties.made < 0.8
    assert answer.unprojected == []


def test_only_a_teams_own_kicker_is_projected(db, upcoming, monkeypatch):
    monkeypatch.setattr(fantasyiq_kicker.model, "load_cached", lambda *args: SteadyKicking())
    alpha, ann, game = upcoming
    spare = _kicker(db, alpha, "Sam Spare")  # listed but has never kicked

    answers = _project(db, [ann, spare], game)

    assert isinstance(answers[("player", ann.id)], base.StatProjection)
    assert isinstance(answers[("player", spare.id)], base.Unavailable)


def test_a_kicker_whose_team_has_too_few_games_is_unavailable(db, monkeypatch):
    monkeypatch.setattr(fantasyiq_kicker.model, "load_cached", lambda *args: SteadyKicking())
    alpha, bravo = _team(db, "Alpha Aces", "ALP"), _team(db, "Bravo Bears", "BRV")
    ann = _kicker(db, alpha, "Ann Kicker")
    fantasyiq_kicker._cache.clear()
    start = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
    game = Game(
        sport="NFL", season="2026", home_team_id=alpha.id, away_team_id=bravo.id,
        start_time=start, week=1, status="scheduled", stats_final=False,
    )  # fmt: skip
    db.add(game)
    db.flush()

    answer = _project(db, [ann], game)[("player", ann.id)]

    assert isinstance(answer, base.Unavailable) and "games of history" in answer.reason


def test_an_untrained_kicker_model_is_an_error(db, upcoming, monkeypatch):
    monkeypatch.setattr(fantasyiq_kicker.model, "load_cached", lambda *args: None)
    _, ann, game = upcoming

    with pytest.raises(base.ProjectionError, match="kicker model hasn't been trained"):
        _project(db, [ann], game)
