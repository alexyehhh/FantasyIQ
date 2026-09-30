"""The depth chart and injury news read from Sleeper's player file (real Postgres for our own
players, a fake Sleeper for the file)."""

import httpx
import pytest

from app.db.models import Player, Team
from app.db.session import SessionLocal
from app.services.projections.news import Feed

PLAYERS = {
    "1": {
        "full_name": "Braelon Allen", "team": "NYJ", "position": "RB",
        "depth_chart_order": 1, "depth_chart_position": "RB", "injury_status": None,
    },
    "2": {
        "full_name": "Breece Hall", "team": "NYJ", "position": "RB",
        "depth_chart_order": 2, "depth_chart_position": "RB",
        "injury_status": "Doubtful", "injury_body_part": "Thigh",
    },
    "3": {
        "full_name": "Wes Receiver", "team": "NYJ", "position": "WR",
        "depth_chart_order": None, "injury_status": "Questionable",
    },
}  # fmt: skip


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def jets(db):
    team = Team(name="New York Jets", abbreviation="NYJ", sport="NFL")
    db.add(team)
    db.flush()
    made = {}
    for name, position in (("Braelon Allen", "RB"), ("Breece Hall", "RB"), ("Wes Receiver", "WR")):
        player = Player(name=name, sport="NFL", team_id=team.id, position=position, active=True)
        db.add(player)
        made[name] = player
    db.flush()
    return team, made


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _feed(handler, clock=None):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Feed(client, clock=clock or Clock(), ttl_seconds=3600)


def test_reads_depth_chart_order_and_who_is_expected_out(db, jets):
    team, players = jets
    feed = _feed(lambda request: httpx.Response(200, json=PLAYERS))

    news = feed.for_teams(db, "NFL", [team.id])

    assert news.depth == {players["Braelon Allen"].id: 1, players["Breece Hall"].id: 2}
    assert news.out_by_team == {team.id: {players["Breece Hall"].id}}  # questionable plays
    assert news.notes[players["Breece Hall"].id] == "Doubtful (Thigh)"


def test_the_file_is_fetched_once_until_it_goes_stale(db, jets):
    team, _ = jets
    clock, calls = Clock(), []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=PLAYERS)

    feed = _feed(handler, clock)
    feed.for_teams(db, "NFL", [team.id])
    feed.for_teams(db, "NFL", [team.id])
    clock.now = 3601
    feed.for_teams(db, "NFL", [team.id])

    assert calls == ["/v1/players/nfl", "/v1/players/nfl"]


def test_an_unreachable_sleeper_gives_no_news_instead_of_an_error(db, jets):
    team, _ = jets
    clock, calls = Clock(), []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    feed = _feed(handler, clock)

    assert feed.for_teams(db, "NFL", [team.id]).depth == {}
    feed.for_teams(db, "NFL", [team.id])
    assert len(calls) == 1  # not retried straight away
    clock.now = 200
    feed.for_teams(db, "NFL", [team.id])
    assert len(calls) == 2


def test_an_unexpected_shape_gives_no_news(db, jets):
    team, _ = jets
    feed = _feed(lambda request: httpx.Response(200, json=["not", "a", "player", "map"]))

    assert feed.for_teams(db, "NFL", [team.id]).out_by_team == {}


def test_only_the_nfl_has_a_depth_chart(db, jets):
    team, players = jets
    nba_team = Team(name="Some Hawks", abbreviation="SOM", sport="NBA")
    db.add(nba_team)
    db.flush()
    guard = Player(name="Gus Guard", sport="NBA", team_id=nba_team.id, position="G", active=True)
    db.add(guard)
    db.flush()
    feed = _feed(
        lambda request: httpx.Response(
            200,
            json={"9": {"full_name": "Gus Guard", "team": "SOM", "position": "G",
                        "depth_chart_order": 1, "injury_status": "Out"}},
        )
    )  # fmt: skip

    news = feed.for_teams(db, "NBA", [nba_team.id])

    assert news.depth == {}
    assert news.out_by_team == {nba_team.id: {guard.id}}
