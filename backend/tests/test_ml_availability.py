"""Teammate availability: who is missing, what their work becomes, and that training and serving
read it the same way."""

import pandas as pd
import pytest

from app.ml.availability import Timeline, attach_training_context
from app.ml.dataset import STATS

STATS_NFL = STATS["NFL"]
TEAM, STARTER, BACKUP, RECEIVER, OTHER_TEAM_RB = 1, 10, 11, 12, 99


def _row(player, game, position, rushes=0, targets=0, season="2026"):
    return {
        "player_id": player,
        "game_id": game,
        "team_id": TEAM,
        "position": position,
        "season": season,
        "start_time": pd.Timestamp("2026-09-01") + pd.Timedelta(days=7 * game),
        **{stat: 0.0 for stat in STATS_NFL},
        "rushing_attempts": float(rushes),
        "receiving_targets": float(targets),
    }


def _schedule(games, season="2026"):
    return pd.DataFrame(
        [
            {
                "team_id": TEAM,
                "game_id": g,
                "season": season,
                "start_time": pd.Timestamp("2026-09-01") + pd.Timedelta(days=7 * g),
            }
            for g in games
        ]
    )


def _timeline(starter_games, all_games):
    rows = []
    for game in all_games:
        if game in starter_games:
            rows.append(_row(STARTER, game, "RB", rushes=15))
        rows.append(_row(BACKUP, game, "RB", rushes=5))
        rows.append(_row(RECEIVER, game, "WR", targets=8))
    history = pd.DataFrame(rows)
    return history, Timeline(history, _schedule(all_games), STATS_NFL)


def test_a_starter_missing_from_the_box_score_frees_his_work_for_the_backup():
    history, timeline = _timeline(starter_games={1, 2, 3, 4}, all_games=[1, 2, 3, 4, 5])
    k = timeline.position_before(TEAM, pd.Timestamp("2026-09-01") + pd.Timedelta(days=35))

    backup = timeline.features_for(BACKUP, TEAM, "2026", k)

    assert backup["vac__rushing_attempts"] == pytest.approx(15)
    assert backup["n_absent"] == 1
    # He is the only running back left, so he takes the starter's whole load; it is newly gone.
    assert backup["inherit__rushing_attempts"] == pytest.approx(15)
    assert backup["new_inherit__rushing_attempts"] == pytest.approx(15)


def test_the_load_goes_to_the_same_position_not_to_receivers():
    _, timeline = _timeline(starter_games={1, 2, 3, 4}, all_games=[1, 2, 3, 4, 5])

    receiver = timeline.features_for(RECEIVER, TEAM, "2026", 4)

    assert receiver["vac__rushing_attempts"] == pytest.approx(15)  # the team lost the carries...
    assert receiver["inherit__rushing_attempts"] == 0  # ...but a receiver doesn't inherit them


def test_a_game_yet_to_be_played_uses_who_is_listed_out():
    _, timeline = _timeline(starter_games={1, 2, 3, 4}, all_games=[1, 2, 3, 4])

    backup = timeline.features_for(BACKUP, TEAM, "2026", 4, out_ids={STARTER})
    nobody = timeline.features_for(BACKUP, TEAM, "2026", 4, out_ids=set())

    assert backup["inherit__rushing_attempts"] == pytest.approx(15)
    assert nobody["inherit__rushing_attempts"] == 0 and nobody["n_absent"] == 0


def test_the_training_and_serving_paths_agree():
    history, timeline = _timeline(starter_games={1, 2, 3, 4}, all_games=[1, 2, 3, 4, 5])
    trained = attach_training_context(history, timeline, STATS_NFL)
    in_game_5 = trained[(trained["player_id"] == BACKUP) & (trained["game_id"] == 5)].iloc[0]

    served = timeline.features_for(BACKUP, TEAM, "2026", 4, out_ids={STARTER})

    for name, value in served.items():
        assert in_game_5[name] == pytest.approx(value), name


def test_a_teammate_back_after_missing_a_game_is_returning():
    _, timeline = _timeline(starter_games={1, 2, 3, 4, 6}, all_games=[1, 2, 3, 4, 5, 6])

    backup = timeline.features_for(BACKUP, TEAM, "2026", 5)  # game 6: starter is back

    assert backup["ret__rushing_attempts"] == pytest.approx(15)
    assert backup["vac__rushing_attempts"] == 0 and backup["n_absent"] == 0


def test_a_players_own_absence_never_counts_against_himself():
    _, timeline = _timeline(starter_games={1, 2, 3, 4}, all_games=[1, 2, 3, 4])

    starter = timeline.features_for(STARTER, TEAM, "2026", 4, out_ids={STARTER})

    assert starter["n_absent"] == 0 and starter["inherit__rushing_attempts"] == 0


def test_last_seasons_players_are_not_counted_as_missing():
    history, _ = _timeline(starter_games={1, 2, 3, 4}, all_games=[1, 2, 3, 4])
    schedule = pd.concat([_schedule([1, 2, 3, 4]), _schedule([5], season="2027")])
    timeline = Timeline(history, schedule.reset_index(drop=True), STATS_NFL)

    backup = timeline.features_for(BACKUP, TEAM, "2027", 4, out_ids={STARTER})

    assert backup["n_absent"] == 0 and backup["vac__rushing_attempts"] == 0


def test_a_game_whose_box_score_is_unavailable_is_left_out_of_the_schedule():
    history, _ = _timeline(starter_games={1, 2, 3, 4}, all_games=[1, 2, 3, 4])
    timeline = Timeline(history, _schedule([1, 2, 3, 4]), STATS_NFL)
    # Only finished games with complete box scores are scheduled, so a team's window never holds an
    # empty game that would make every player look absent.
    assert [g.game_id for g in timeline.teams[TEAM]] == [1, 2, 3, 4]
    assert all(g.members for g in timeline.teams[TEAM])
