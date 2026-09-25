"""Projections end to end through the service (real Postgres, rolled back after)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import (
    Game,
    Player,
    PlayerGameStatsNFL,
    Team,
    TeamGameStatsNFL,
)
from app.db.session import SessionLocal
from app.services.projections import service
from app.services.projections.base import KickBucket, UnknownSource
from app.services.projections.expected_scoring import score_expected_defense
from app.services.scoring import ScoringConfig, default_config
from tests.projection_sources import install

NFL = default_config("NFL")
NBA = default_config("NBA")
_START = datetime(2026, 9, 10, 20, 0)
RECEIVER = {"receptions": 8, "receiving_yards": 50}  # 13 PPR points


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _team(db, name, abbreviation, sport="NFL"):
    team = Team(name=name, abbreviation=abbreviation, sport=sport)
    db.add(team)
    db.flush()
    return team


def _game(db, home, away, week, status="final", start=None):
    game = Game(
        sport="NFL",
        season="2026",
        home_team_id=home.id,
        away_team_id=away.id,
        start_time=start or _START + timedelta(days=7 * week),
        week=week,
        status=status,
    )
    db.add(game)
    db.flush()
    return game


def _player(db, team, name, position="WR", **kwargs):
    player = Player(name=name, sport="NFL", team_id=team.id, position=position, **kwargs)
    db.add(player)
    db.flush()
    return player


@pytest.fixture
def league(db):
    """Alpha hosts Bravo: three finished games (weeks 1-3) then an upcoming one in week 4."""
    alpha, bravo = _team(db, "Alpha Aces", "ALP"), _team(db, "Bravo Bears", "BRV")
    past = [_game(db, alpha, bravo, week) for week in (1, 2, 3)]
    soon = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
    upcoming = _game(db, alpha, bravo, 4, status="scheduled", start=soon)
    return alpha, bravo, past, upcoming


def _history(db, player, games, lines):
    """Past games' stat lines as (receptions, yards), the history the spread is sized from."""
    for game, (receptions, yards) in zip(games, lines, strict=True):
        db.add(
            PlayerGameStatsNFL(
                player_id=player.id, game_id=game.id, receptions=receptions, receiving_yards=yards
            )
        )
    db.flush()


def _run(db, **kwargs):
    kwargs.setdefault("sport", "NFL")
    kwargs.setdefault("source", "static")
    kwargs.setdefault("config", NFL)
    return service.project(db, **kwargs)


def test_a_projected_stat_line_is_scored_under_the_config_for_the_next_game(
    db, league, monkeypatch
):
    alpha, bravo, _, upcoming = league
    wes = _player(db, alpha, "Wes Receiver", headshot_url="http://x/wes.png")
    install(monkeypatch, {"Wes Receiver": RECEIVER})

    (result,) = _run(db, player_ids=[wes.id])

    assert result.status == "ok" and result.fantasy_points == 13.0
    assert result.stats == {"receptions": 8, "receiving_yards": 50}
    assert result.game.id == upcoming.id and result.opponent.id == bravo.id and result.is_home
    assert result.headshot_url == "http://x/wes.png" and result.source == "static"


def test_the_same_stats_are_worth_what_the_leagues_own_scoring_says(db, league, monkeypatch):
    alpha, *_ = league
    wes = _player(db, alpha, "Wes Receiver")
    install(monkeypatch, {"Wes Receiver": RECEIVER})
    standard = ScoringConfig(name="Standard", sport="NFL", player_weights={"receiving_yards": 0.1})

    (ppr,) = _run(db, player_ids=[wes.id])
    (no_ppr,) = _run(db, player_ids=[wes.id], config=standard)

    assert ppr.fantasy_points - no_ppr.fantasy_points == 8


def test_a_player_the_source_has_nothing_for_is_unavailable_with_a_reason(db, league, monkeypatch):
    alpha, *_ = league
    rookie = _player(db, alpha, "Rory Rookie")
    install(monkeypatch, {})

    (result,) = _run(db, player_ids=[rookie.id])

    assert result.status == "unavailable" and result.fantasy_points is None
    assert "Not in the static source" in result.notes


def test_a_kickers_expected_kicks_are_scored_by_distance_bracket(db, league, monkeypatch):
    alpha, *_ = league
    kicker = _player(db, alpha, "Kip Kicker", "PK")
    # default brackets: 40-49 yards is 4 points made, and -2 missed
    install(
        monkeypatch,
        {"Kip Kicker": {"extra_points_made": 2, "extra_point_attempts": 2}},
        {"Kip Kicker": [KickBucket(40, 49, made=1.5, missed=0.5)]},
    )

    (result,) = _run(db, player_ids=[kicker.id])

    assert result.fantasy_points == pytest.approx(2 + 1.5 * 4 - 0.5 * 2)
    assert not result.approximate


def test_a_team_defense_is_projected_and_scored_with_its_points_allowed_brackets(
    db, league, monkeypatch
):
    alpha, *_ = league
    stats = {"sacks": 3, "interceptions": 1, "points_allowed": 17.5}
    install(monkeypatch, {"Alpha Aces D/ST": stats})

    (result,) = _run(db, defense_ids=[alpha.id])

    assert result.kind == "defense" and result.name == "Alpha Aces D/ST"
    assert result.fantasy_points == pytest.approx(score_expected_defense(NFL, stats).points)


def test_a_player_ruled_out_projects_zero_without_asking_the_source(db, league, monkeypatch):
    alpha, *_ = league
    hurt = _player(db, alpha, "Hank Hurt", injury_status="Out")
    fine = _player(db, alpha, "Fay Fine")
    source = install(monkeypatch, {"Fay Fine": RECEIVER})

    results = {r.name: r for r in _run(db, player_ids=[hurt.id, fine.id])}

    assert results["Hank Hurt"].status == "out" and results["Hank Hurt"].fantasy_points == 0
    assert source.asked == ["Fay Fine"]


def test_an_uncertain_players_projection_carries_a_warning(db, league, monkeypatch):
    alpha, *_ = league
    wes = _player(db, alpha, "Wes Receiver", injury_status="Questionable")
    install(monkeypatch, {"Wes Receiver": RECEIVER})

    (result,) = _run(db, player_ids=[wes.id])

    assert result.status == "ok"
    assert any("Questionable" in note for note in result.notes)


def test_the_best_projection_comes_first_and_those_without_a_number_last(db, league, monkeypatch):
    alpha, *_ = league
    low, high, nobody = (_player(db, alpha, n) for n in ("Lou Low", "Hal High", "Nate Nobody"))
    install(
        monkeypatch,
        {"Lou Low": {"receptions": 1}, "Hal High": {"receptions": 9, "receiving_yards": 120}},
    )

    results = _run(db, player_ids=[nobody.id, low.id, high.id])

    assert [r.name for r in results] == ["Hal High", "Lou Low", "Nate Nobody"]


def test_a_week_picks_that_weeks_game_and_a_week_without_one_is_a_bye(db, league, monkeypatch):
    alpha, _, _, upcoming = league
    wes = _player(db, alpha, "Wes Receiver")
    install(monkeypatch, {"Wes Receiver": RECEIVER})

    (in_week_four,) = _run(db, player_ids=[wes.id], week=4)
    (bye,) = _run(db, player_ids=[wes.id], week=9)

    assert in_week_four.game.id == upcoming.id
    assert bye.status == "no_game" and any("bye" in note for note in bye.notes)


def test_a_game_that_has_already_been_played_says_so(db, league, monkeypatch):
    alpha, _, past, _ = league
    wes = _player(db, alpha, "Wes Receiver")
    install(monkeypatch, {"Wes Receiver": RECEIVER})

    (result,) = _run(db, player_ids=[wes.id], week=3)

    assert result.game.id == past[2].id
    assert "This game has been played." in result.notes


def test_a_free_agent_has_no_game(db, monkeypatch):
    free = Player(name="Fran Freeagent", sport="NFL", position="WR")
    db.add(free)
    db.flush()
    install(monkeypatch, {})

    (result,) = _run(db, player_ids=[free.id])

    assert result.status == "no_game"


def test_each_scored_player_gets_a_range_and_a_chance_of_scoring_the_most(db, league, monkeypatch):
    alpha, _, past, _ = league
    high = _player(db, alpha, "Hal High")
    low = _player(db, alpha, "Lou Low")
    _history(db, high, past, [(9, 120), (9, 120), (9, 120)])
    install(
        monkeypatch,
        {"Hal High": {"receptions": 9, "receiving_yards": 120}, "Lou Low": {"receptions": 1}},
    )

    best, other = _run(db, player_ids=[low.id, high.id])

    assert best.name == "Hal High"
    assert best.low < best.fantasy_points < best.high
    assert best.spread_basis == "blended" and best.games_sampled == 3  # three games of history
    assert other.spread_basis == "position" and other.games_sampled == 0  # none: typical spread
    assert best.chance_best > 0.9
    assert best.chance_best + other.chance_best == pytest.approx(1, abs=0.01)


def test_a_player_whose_game_is_over_is_still_projected_but_takes_no_part_in_the_odds(
    db, league, monkeypatch
):
    alpha, _, _, upcoming = league
    upcoming.status = "final"  # Alpha's week 4 game has been played
    charlie, delta = _team(db, "Charlie Chiefs", "CHA"), _team(db, "Delta Dogs", "DLT")
    _game(db, charlie, delta, 4, status="scheduled", start=upcoming.start_time)
    played = _player(db, alpha, "Pat Played")
    open_a, open_b = _player(db, charlie, "Ann Open"), _player(db, charlie, "Bea Open")
    install(
        monkeypatch,
        {
            "Pat Played": {"receptions": 30},
            "Ann Open": {"receptions": 9},
            "Bea Open": {"receptions": 8},
        },
    )

    results = {r.name: r for r in _run(db, player_ids=[played.id, open_a.id, open_b.id], week=4)}

    assert results["Pat Played"].status == "ok" and results["Pat Played"].fantasy_points == 30
    assert results["Pat Played"].game.status == "final"
    assert results["Pat Played"].chance_best is None
    chances = results["Ann Open"].chance_best + results["Bea Open"].chance_best
    assert chances == pytest.approx(1, abs=0.01)


def test_the_range_never_changes_the_projection(db, league, monkeypatch):
    alpha, _, past, _ = league
    wes = _player(db, alpha, "Wes Receiver")
    install(monkeypatch, {"Wes Receiver": RECEIVER})
    (before,) = _run(db, player_ids=[wes.id])

    _history(db, wes, past, [(20, 300), (0, 0), (20, 300)])  # a wild history
    (after,) = _run(db, player_ids=[wes.id])

    assert after.fantasy_points == before.fantasy_points == 13.0
    assert after.std != before.std


def test_a_lone_player_has_a_range_but_no_chance_to_compare(db, league, monkeypatch):
    alpha, *_ = league
    wes = _player(db, alpha, "Wes Receiver")
    install(monkeypatch, {"Wes Receiver": RECEIVER})

    (result,) = _run(db, player_ids=[wes.id])

    assert result.chance_best is None and result.std > 0


def test_the_current_week_is_that_of_the_earliest_game_not_yet_finished(db, league):
    _, _, _, upcoming = league

    assert service.current_week(db, "NFL") == 4  # weeks 1-3 are final
    assert service.current_week(db, "NBA") is None
    # once nothing is left to play, the last game's week
    upcoming.status = "final"
    upcoming.start_time = datetime(2027, 1, 1)  # the season's last game
    db.flush()
    assert service.current_week(db, "NFL") == 4


def _slot_league(db, league, monkeypatch, extra=()):
    alpha, *_ = league
    wes, wanda, rex = (
        _player(db, alpha, "Wes Receiver"),
        _player(db, alpha, "Wanda Wideout"),
        _player(db, alpha, "Rex Runner", "RB"),
    )
    lines = {
        "Wes Receiver": {"receptions": 4},
        "Wanda Wideout": {"receptions": 9},
        "Rex Runner": {"receptions": 20},
        **dict(extra),
    }
    return (wes, wanda, rex), install(monkeypatch, lines)


def _top(db, slot, **kwargs):
    kwargs.setdefault("sport", "NFL")
    kwargs.setdefault("source", "static")
    kwargs.setdefault("config", NFL)
    return service.top_players(db, slot=slot, **kwargs)


def test_top_players_ranks_everyone_the_source_projects_at_a_slots_positions(
    db, league, monkeypatch
):
    _slot_league(db, league, monkeypatch)

    wr, wr_total = _top(db, "WR")
    flex, flex_total = _top(db, "FLEX", limit=2)

    assert [r.name for r in wr] == ["Wanda Wideout", "Wes Receiver"] and wr_total == 2
    assert [r.name for r in flex] == ["Rex Runner", "Wanda Wideout"] and flex_total == 3


def test_a_player_with_no_games_this_season_is_still_ranked_if_the_source_projects_them(
    db, league, monkeypatch
):
    alpha, *_ = league
    _player(db, alpha, "Rory Rookie")  # no stat lines at all
    _slot_league(db, league, monkeypatch, {"Rory Rookie": {"receptions": 12}})

    wr, _ = _top(db, "WR")

    assert wr[0].name == "Rory Rookie"


def test_pages_continue_where_the_last_one_ended_and_report_the_total(db, league, monkeypatch):
    alpha, *_ = league
    lines = {}
    for i in range(7):
        _player(db, alpha, f"Receiver {i}")
        lines[f"Receiver {i}"] = {"receptions": 10 - i}
    install(monkeypatch, lines)

    first, total = _top(db, "WR", limit=3)
    second, _ = _top(db, "WR", limit=3, offset=3)
    last, _ = _top(db, "WR", limit=3, offset=6)
    beyond, beyond_total = _top(db, "WR", limit=3, offset=30)

    assert total == 7
    assert [r.name for r in first] == ["Receiver 0", "Receiver 1", "Receiver 2"]
    assert [r.name for r in second] == ["Receiver 3", "Receiver 4", "Receiver 5"]
    assert [r.name for r in last] == ["Receiver 6"]
    assert beyond == [] and beyond_total == 7


def test_top_players_leaves_out_anyone_ruled_out_or_doubtful_but_keeps_questionable(
    db, league, monkeypatch
):
    alpha, *_ = league
    for name, status in (
        ("Hank Hurt", "Out"),
        ("Ivy Reserve", "Injured Reserve"),
        ("Dan Doubtful", "Doubtful"),
        ("Quinn Questionable", "Questionable"),
    ):
        _player(db, alpha, name, injury_status=status)
    _slot_league(
        db,
        league,
        monkeypatch,
        {name: {"receptions": 50} for name in ("Hank Hurt", "Ivy Reserve", "Dan Doubtful")}
        | {"Quinn Questionable": {"receptions": 1}},
    )

    wr, total = _top(db, "WR")

    names = [r.name for r in wr]
    assert names == ["Wanda Wideout", "Wes Receiver", "Quinn Questionable"] and total == 3


def test_a_doubtful_player_named_in_a_comparison_is_still_projected_with_a_warning(
    db, league, monkeypatch
):
    alpha, *_ = league
    dan = _player(db, alpha, "Dan Doubtful", injury_status="Doubtful")
    install(monkeypatch, {"Dan Doubtful": RECEIVER})

    (result,) = _run(db, player_ids=[dan.id])

    assert result.status == "ok" and any("Doubtful" in note for note in result.notes)


def test_top_players_asks_the_source_for_the_current_week_and_the_slots_positions(
    db, league, monkeypatch
):
    _, source = _slot_league(db, league, monkeypatch)

    _top(db, "flex")

    sport, week, day, positions, defenses = source.ranked_for
    assert (sport, week, day, defenses) == ("NFL", 4, None, False)
    assert positions == ["RB", "FB", "WR", "TE"]


def test_the_dst_slot_ranks_team_defenses(db, league, monkeypatch):
    install(
        monkeypatch,
        {
            "Alpha Aces D/ST": {"sacks": 6, "points_allowed": 17},
            "Bravo Bears D/ST": {"sacks": 1, "points_allowed": 17},
        },
    )

    top, total = _top(db, "dst")

    assert [r.name for r in top] == ["Alpha Aces D/ST", "Bravo Bears D/ST"] and total == 2
    assert all(r.kind == "defense" for r in top)


def test_an_unknown_slot_is_rejected(db):
    with pytest.raises(service.ProjectionInputError, match="Unknown NFL slot"):
        service.top_players(db, sport="NFL", slot="IDP", source="sleeper", config=NFL)


def test_requests_that_cannot_be_answered_are_rejected(db, league, monkeypatch):
    alpha, *_ = league
    wes = _player(db, alpha, "Wes Receiver")
    install(monkeypatch, {})

    with pytest.raises(service.ProjectionInputError, match="Unknown player ids"):
        _run(db, player_ids=[wes.id, 0])
    with pytest.raises(service.ProjectionInputError, match="Unknown defense ids"):
        _run(db, defense_ids=[0])
    with pytest.raises(service.ProjectionInputError, match="can't score"):
        _run(db, player_ids=[wes.id], config=NBA)
    with pytest.raises(service.ProjectionInputError, match="Every player"):
        _run(db, sport="NBA", config=NBA, player_ids=[wes.id])
    with pytest.raises(service.ProjectionInputError, match="week only applies"):
        _run(db, sport="NBA", config=NBA, player_ids=[], week=3)
    with pytest.raises(UnknownSource):
        _run(db, source="crystal_ball", player_ids=[wes.id])


# Guard against the removed sources coming back by accident: the projection level must come from
# an outside source alone.
def test_recent_form_and_blend_are_not_sources():
    from app.services.projections.base import PROVIDERS

    assert "recent_form" not in PROVIDERS and "blend" not in PROVIDERS
    assert TeamGameStatsNFL  # (history for a defense's range is still read from its own lines)
