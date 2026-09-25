"""The on-request refresh of live and just-finished games (data_pipeline/refresh.py).

Selection and the orchestration (cooldowns, one bad game not stopping the rest) are tested against
fake ESPN clients; a last group runs a game from scheduled through live to final over the real NBA
ingest, which is the path a page load takes.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.models import Game, PlayerGameStats, Team
from app.db.session import SessionLocal
from data_pipeline import nba_ingest
from data_pipeline.espn import ESPNRateLimited
from data_pipeline.espn_common import IngestionError
from data_pipeline.refresh import (
    FAILURE_BACKOFF,
    NOT_STARTED_LOOKBACK,
    UNLOADED_LOOKBACK,
    LiveRefresher,
    Pipeline,
    select_refreshable,
)

NOW = datetime(2026, 9, 25, 12, 0)  # naive UTC, as stored
COOLDOWN = timedelta(seconds=30)  # the default live_refresh_cooldown_seconds


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _game(db, external_id, *, sport="NFL", status="final", start=None, stats_final=False):
    home = Team(name=f"{external_id} home", abbreviation="HOM", sport=sport)
    away = Team(name=f"{external_id} away", abbreviation="AWY", sport=sport)
    db.add_all([home, away])
    db.flush()
    game = Game(
        external_id=external_id,
        sport=sport,
        season="2026",
        home_team_id=home.id,
        away_team_id=away.id,
        start_time=start or NOW - timedelta(hours=3),
        status=status,
        stats_final=stats_final,
    )
    db.add(game)
    db.flush()
    return game


# --- Which games are worth asking ESPN about -------------------------------------------------


def test_a_game_in_progress_is_always_refreshed(db):
    _game(db, "live", status="in_progress")
    _game(db, "live-long-ago", status="in_progress", start=NOW - timedelta(days=30))

    assert select_refreshable(db, "NFL", NOW) == ["live", "live-long-ago"]


def test_a_game_the_schedule_still_calls_scheduled_is_refreshed_once_it_has_started(db):
    _game(db, "started", status="scheduled", start=NOW - timedelta(minutes=5))
    _game(db, "later-today", status="scheduled", start=NOW + timedelta(hours=2))
    _game(
        db, "long-gone", status="scheduled", start=NOW - NOT_STARTED_LOOKBACK - timedelta(hours=1)
    )

    assert select_refreshable(db, "NFL", NOW) == ["started"]


def test_a_finished_game_is_refreshed_until_a_box_score_taken_after_it_ended_is_stored(db):
    _game(db, "just-ended")
    _game(db, "loaded", stats_final=True)
    _game(db, "backlog", start=NOW - UNLOADED_LOOKBACK - timedelta(days=1))

    assert select_refreshable(db, "NFL", NOW) == ["just-ended"]


def test_games_are_selected_per_sport_newest_first(db):
    _game(db, "nfl-older", start=NOW - timedelta(days=2))
    _game(db, "nfl-newer", start=NOW - timedelta(hours=5))
    _game(db, "nba", sport="NBA")

    assert select_refreshable(db, "NFL", NOW) == ["nfl-newer", "nfl-older"]
    assert select_refreshable(db, "NBA", NOW) == ["nba"]


# --- Orchestration, against fakes ------------------------------------------------------------


class FakeClient:
    """Stands in for an ESPN client: `payloads` maps a game id to a payload tuple, or to the
    exception fetching it should raise."""

    def __init__(self, payloads):
        self.payloads = payloads
        self.asked: list[str] = []
        self.closed = False

    def get_game(self, game_id):
        self.asked.append(game_id)
        payload = self.payloads[game_id]
        if isinstance(payload, Exception):
            raise payload
        return payload

    def close(self):
        self.closed = True


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now

    def advance(self, delta):
        self.now += delta


def _refresher(client, clock, ingest):
    pipelines = {
        sport: Pipeline(make_client=lambda _timeout: client, ingest=ingest)
        for sport in ("NBA", "NFL")
    }
    return LiveRefresher(pipelines, clock=clock)


def test_nothing_due_builds_no_client_at_all(db):
    _game(db, "loaded", stats_final=True)
    _game(db, "upcoming", status="scheduled", start=NOW + timedelta(days=1))

    def no_client(_timeout):
        raise AssertionError("ESPN must not be contacted when nothing is due")

    refresher = LiveRefresher(
        {sport: Pipeline(no_client, lambda *_: 0) for sport in ("NBA", "NFL")}, clock=Clock()
    )

    report = refresher.refresh(db)

    assert (report.refreshed, report.failed) == ([], {})


def test_a_due_game_is_fetched_stored_and_not_asked_again_within_the_cooldown(db):
    _game(db, "live", status="in_progress")
    client = FakeClient({"live": ("payload",)})
    stored = []
    clock = Clock()
    refresher = _refresher(client, clock, lambda _db, *payload: stored.append(payload))

    assert refresher.refresh(db).refreshed == ["live"]
    assert client.closed
    assert stored == [("payload",)]

    clock.advance(COOLDOWN - timedelta(seconds=1))
    assert refresher.refresh(db).refreshed == []  # a reload right after must not hit ESPN again
    assert client.asked == ["live"]

    clock.advance(timedelta(seconds=2))
    assert refresher.refresh(db).refreshed == ["live"]
    assert client.asked == ["live", "live"]


def test_a_game_that_fails_is_left_alone_for_a_while_and_does_not_stop_the_others(db):
    _game(db, "bad", status="in_progress", start=NOW - timedelta(hours=1))
    _game(db, "good", status="in_progress")
    client = FakeClient({"bad": IngestionError("ESPN said no"), "good": ("payload",)})
    clock = Clock()
    refresher = _refresher(client, clock, lambda *_: 0)

    report = refresher.refresh(db)

    assert report.refreshed == ["good"]
    assert report.failed == {"bad": "IngestionError: ESPN said no"}

    clock.advance(COOLDOWN + timedelta(seconds=1))
    refresher.refresh(db)
    assert client.asked.count("bad") == 1  # still backing off

    clock.advance(FAILURE_BACKOFF)
    refresher.refresh(db)
    assert client.asked.count("bad") == 2


def test_a_game_is_not_penalized_when_espn_is_rate_limiting_us(db):
    _game(db, "live", status="in_progress")
    limited = IngestionError("ESPN rejected or could not serve the summary")
    limited.__cause__ = ESPNRateLimited("holding off 60s")  # as the ingest clients raise it
    client = FakeClient({"live": limited})
    clock = Clock()
    refresher = _refresher(client, clock, lambda *_: 0)

    assert list(refresher.refresh(db).failed) == ["live"]
    clock.advance(timedelta(seconds=31))  # well inside the 5 minutes an ordinary failure waits
    refresher.refresh(db)

    assert client.asked == ["live", "live"]


def test_a_game_whose_ingest_fails_is_rolled_back_without_losing_the_others(db):
    _game(db, "bad", status="in_progress", start=NOW - timedelta(hours=1))
    _game(db, "good", status="in_progress")
    client = FakeClient({"bad": ("bad",), "good": ("good",)})

    def ingest(session, name):
        session.add(Team(name=f"stored by {name}", abbreviation="TMP", sport="NFL"))
        session.flush()
        if name == "bad":
            raise IngestionError("does not reconcile")

    report = _refresher(client, Clock(), ingest).refresh(db)

    assert report.refreshed == ["good"]
    assert list(report.failed) == ["bad"]
    stored = set(db.scalars(select(Team.name).where(Team.name.like("stored by %"))))
    assert stored == {"stored by good"}


# --- A game from kickoff to final, over the real NBA ingest ------------------------------------


def _nba_summary(state: str, home: int, away: int, points: int) -> dict:
    return {
        "header": {
            "id": "g-nba",
            "season": {"year": 2027},
            "competitions": [
                {
                    "date": "2026-09-25T00:15:00Z",
                    "competitors": [
                        {
                            "homeAway": "home",
                            "score": str(home),
                            "team": {"id": "10", "displayName": "Home", "abbreviation": "HOM"},
                        },
                        {
                            "homeAway": "away",
                            "score": str(away),
                            "team": {"id": "6", "displayName": "Away", "abbreviation": "AWY"},
                        },
                    ],
                }
            ],
            "status": {"type": {"state": state}},
        },
        "boxscore": {
            "players": [
                {
                    "team": {"id": "10"},
                    "statistics": [
                        {
                            "keys": ["MIN", "PTS"],
                            "athletes": [
                                {
                                    "athlete": {
                                        "id": "70",
                                        "firstName": "Jaylen",
                                        "lastName": "Brown",
                                        "displayName": "Jaylen Brown",
                                        "position": {"abbreviation": "G"},
                                    },
                                    "statistics": ["20", points],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    }


def _nba_refresher(summary_factory, clock):
    """A refresher whose NBA pipeline is the real ingest fed by `summary_factory`."""
    return LiveRefresher(
        {
            "NBA": Pipeline(
                lambda _timeout: nba_ingest.ESPNNBAClient(summary_factory=summary_factory),
                nba_ingest.ingest_game,
            ),
            "NFL": Pipeline(lambda _timeout: FakeClient({}), lambda *_: 0),
        },
        clock=clock,
    )


def test_a_game_goes_from_scheduled_to_live_to_final_as_pages_are_loaded(db):
    home = Team(external_id="nba:10", name="Home", abbreviation="HOM", sport="NBA")
    away = Team(external_id="nba:6", name="Away", abbreviation="AWY", sport="NBA")
    db.add_all([home, away])
    db.flush()
    game = Game(
        external_id="g-nba",
        sport="NBA",
        season="2026-27",
        home_team_id=home.id,
        away_team_id=away.id,
        start_time=datetime(2026, 9, 25, 0, 15),
        status="scheduled",
    )
    db.add(game)
    db.flush()

    summary = {"now": _nba_summary("in", 20, 18, 12)}
    clock = Clock()
    clock.now = datetime(2026, 9, 25, 1, 0)
    refresher = _nba_refresher(lambda _id: summary["now"], clock)

    def points():
        return db.scalar(select(PlayerGameStats.points).join(Game).where(Game.id == game.id))

    # Live: the running total is stored, the game is in progress and not yet trusted as complete.
    assert refresher.refresh(db).refreshed == ["g-nba"]
    db.refresh(game)
    assert (game.status, game.stats_final, game.home_score, game.away_score) == (
        "in_progress", False, 20, 18,
    )
    assert points() == 12

    # A reload within the cooldown reads what is stored.
    summary["now"] = _nba_summary("in", 24, 18, 15)
    assert refresher.refresh(db).refreshed == []
    assert points() == 12

    # A later reload picks up the new total.
    clock.advance(COOLDOWN + timedelta(seconds=1))
    assert refresher.refresh(db).refreshed == ["g-nba"]
    assert points() == 15

    # After the buzzer: final, the totals are the final ones, one row (upserted, not duplicated).
    summary["now"] = _nba_summary("post", 101, 99, 31)
    clock.advance(COOLDOWN + timedelta(seconds=1))
    assert refresher.refresh(db).refreshed == ["g-nba"]
    db.refresh(game)
    assert (game.status, game.stats_final, game.home_score, game.away_score) == (
        "final", True, 101, 99,
    )
    assert points() == 31
    assert db.scalar(select(func.count()).select_from(PlayerGameStats)) == 1

    # Done: nothing is fetched for it any more.
    clock.advance(timedelta(hours=1))
    assert select_refreshable(db, "NBA", clock.now) == []
    assert refresher.refresh(db).refreshed == []


def test_a_finished_game_without_a_posted_box_score_is_tried_again_not_marked_loaded(db):
    home = Team(external_id="nba:10", name="Home", abbreviation="HOM", sport="NBA")
    away = Team(external_id="nba:6", name="Away", abbreviation="AWY", sport="NBA")
    db.add_all([home, away])
    db.flush()
    game = Game(
        external_id="g-nba",
        sport="NBA",
        season="2026-27",
        home_team_id=home.id,
        away_team_id=away.id,
        start_time=datetime(2026, 9, 25, 0, 15),
        status="scheduled",
    )
    db.add(game)
    db.flush()
    empty = _nba_summary("post", 101, 99, 0)
    empty["boxscore"] = {"players": []}
    clock = Clock()
    clock.now = datetime(2026, 9, 25, 4, 0)
    refresher = _nba_refresher(lambda _id: empty, clock)

    refresher.refresh(db)

    db.refresh(game)
    assert (game.status, game.stats_final) == ("final", False)
    assert select_refreshable(db, "NBA", clock.now) == ["g-nba"]
