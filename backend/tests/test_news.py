"""Player news end to end: the Gemini budget, saving ESPN's articles, reading them with a stubbed
Gemini, and what the projection feed does with the facts (real Postgres, fake ESPN and Gemini)."""

from datetime import datetime, timedelta

import httpx
import pytest
from google.genai import errors as genai_errors

from app.ai.budget import GeminiBudget
from app.ai.rate_limit import RateLimitExceeded
from app.db.models import Game, GeminiCall, NewsItem, Player, Team
from app.db.session import SessionLocal
from app.services.news import extract
from app.services.projections.news import Feed
from data_pipeline.espn import ESPNClient
from data_pipeline.espn_news import refresh_news, tagged_athlete_ids

NOW = datetime(2026, 10, 2, 20, 0)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        # The budget commits (a count must survive a failed request), so clear what these tests
        # wrote; the other tests expect these tables empty.
        for table in (NewsItem, GeminiCall, Game, Player, Team):
            session.query(table).delete()
        session.commit()
        session.close()


@pytest.fixture
def seahawks(db):
    team = Team(name="Seattle Seahawks", abbreviation="SEA", sport="NFL", external_id="nfl:26")
    db.add(team)
    db.flush()
    players = {}
    for name, position, external_id in (
        ("Zach Charbonnet", "RB", "4426385"),
        ("Jadarian Price", "RB", "5001"),
    ):
        player = Player(
            name=name, sport="NFL", team_id=team.id, position=position, external_id=external_id
        )
        db.add(player)
        players[name] = player
    db.flush()
    return team, players


def _article(article_id, headline, athlete_ids=(), published="2026-10-02T18:00:00Z"):
    return {
        "id": article_id,
        "headline": headline,
        "description": f"{headline} in detail.",
        "published": published,
        "categories": [{"type": "athlete", "athleteId": a} for a in athlete_ids]
        + [{"type": "team", "teamId": 26}],
    }


def _espn(articles):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["team"] == "26"
        return httpx.Response(200, json={"articles": articles})

    return ESPNClient(
        client=httpx.Client(
            base_url="https://site.api.espn.com", transport=httpx.MockTransport(handler)
        )
    )


# --- The budget ---------------------------------------------------------------------------------


def test_the_budget_refuses_a_call_over_the_minute_limit_and_says_when_to_retry(db):
    clock = [NOW]
    budget = GeminiBudget("m", per_minute=2, per_day=100, clock=lambda: clock[0])

    budget.reserve(db, "news")
    clock[0] += timedelta(seconds=10)
    budget.reserve(db, "news")
    clock[0] += timedelta(seconds=10)
    with pytest.raises(RateLimitExceeded) as raised:
        budget.reserve(db, "news")
    assert raised.value.retry_after == pytest.approx(40)
    clock[0] += timedelta(seconds=41)
    budget.reserve(db, "news")  # the first has aged out of the minute


def test_the_budget_refuses_a_call_over_the_daily_limit_even_after_a_restart(db):
    clock = [NOW]
    first = GeminiBudget("m", per_minute=100, per_day=3, clock=lambda: clock[0])
    for _ in range(3):
        first.reserve(db, "news")
        clock[0] += timedelta(hours=1)

    # A new object, as after a worker restart: the count lives in the database.
    again = GeminiBudget("m", per_minute=100, per_day=3, clock=lambda: clock[0])
    assert again.remaining_today(db) == 0
    with pytest.raises(RateLimitExceeded):
        again.reserve(db, "news")
    clock[0] = NOW + timedelta(days=1, minutes=1)
    again.reserve(db, "news")


def test_the_budget_counts_each_model_on_its_own(db):
    clock = [NOW]
    GeminiBudget("a", per_minute=1, per_day=1, clock=lambda: clock[0]).reserve(db, "news")
    GeminiBudget("b", per_minute=1, per_day=1, clock=lambda: clock[0]).reserve(db, "news")


# --- Saving ESPN's news -------------------------------------------------------------------------


def test_tagged_athletes_are_read_in_order_without_repeats():
    raw = _article(1, "x", ["4426385", "5001", "4426385"])
    assert tagged_athlete_ids(raw) == ["4426385", "5001"]


def test_new_articles_are_saved_once_and_only_those_naming_our_players_are_read(db, seahawks):
    articles = [
        _article(1, "Price ruled out", ["5001"]),
        _article(2, "Week 4 rankings"),
        _article(3, "Unknown player", ["999999"]),
        _article(4, "Old news", ["5001"], published="2026-09-01T00:00:00Z"),
    ]
    client = _espn(articles)

    report = refresh_news(db, client, "NFL", now=NOW)
    again = refresh_news(db, client, "NFL", now=NOW)

    assert (report.teams, report.saved, again.saved) == (1, 4, 0)
    items = {i.external_id: i for i in db.query(NewsItem)}
    assert {k: v.status for k, v in items.items()} == {
        "1": "pending",
        "2": "skipped",
        "3": "skipped",
        "4": "skipped",
    }
    assert items["1"].player_ids == [seahawks[1]["Jadarian Price"].id]
    assert items["1"].published_at == datetime(2026, 10, 2, 18, 0)


# --- Reading it with Gemini ---------------------------------------------------------------------


class _Response:
    def __init__(self, text):
        self.text = text


class _Gemini:
    """A stand-in client: answers with `reply(prompt)` and records every call."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.models = self

    def generate_content(self, *, model, contents, config):
        self.calls.append((model, contents, config))
        result = self.reply(contents)
        if isinstance(result, Exception):
            raise result
        return _Response(result)


def _pending(db, team, player, headline="Price ruled out", minutes=0):
    item = NewsItem(
        sport="NFL",
        external_id=f"x{headline}{minutes}",
        team_id=team.id,
        headline=headline,
        description="Out Sunday.",
        published_at=NOW - timedelta(minutes=minutes),
        player_ids=[player.id],
        status="pending",
    )
    db.add(item)
    db.flush()
    return item


def _answer(item, player_id, **fields):
    import json

    fact = {
        "item_id": item.id,
        "player_id": player_id,
        "availability": "out",
        "role": "unclear",
        "about_next_game": True,
        "note": "Ruled out for Sunday.",
    } | fields
    return json.dumps({"facts": [fact]})


def _budget():
    return GeminiBudget("lite", per_minute=100, per_day=100)


def test_extraction_saves_the_facts_and_marks_the_article_read(db, seahawks):
    team, players = seahawks
    price = players["Jadarian Price"]
    item = _pending(db, team, price)
    gemini = _Gemini(lambda prompt: _answer(item, price.id))

    report = extract.extract_pending(db, _budget(), client=gemini, now=NOW)

    assert (report.calls, report.read, report.facts) == (1, 1, 1)
    db.refresh(item)
    assert item.status == "done" and item.read_at == NOW
    assert item.facts[0]["availability"] == "out" and item.facts[0]["player_id"] == price.id
    model, prompt, config = gemini.calls[0]
    assert model == "lite" and "Price ruled out" in prompt and "Jadarian Price" in prompt
    assert config.response_mime_type == "application/json"
    assert db.query(GeminiCall).count() == 1


def test_facts_about_players_the_article_did_not_tag_are_dropped(db, seahawks):
    team, players = seahawks
    item = _pending(db, team, players["Jadarian Price"])
    other = players["Zach Charbonnet"]
    gemini = _Gemini(lambda prompt: _answer(item, other.id))

    report = extract.extract_pending(db, _budget(), client=gemini, now=NOW)

    assert report.facts == 0
    db.refresh(item)
    assert item.status == "done" and item.facts == []


def test_an_unusable_answer_is_retried_once_then_given_up_on(db, seahawks):
    team, players = seahawks
    item = _pending(db, team, players["Jadarian Price"])
    gemini = _Gemini(lambda prompt: "not json")

    report = extract.extract_pending(db, _budget(), client=gemini, now=NOW)

    assert report.calls == 2 and report.failed == 1
    db.refresh(item)
    assert item.status == "failed" and item.attempts == 2


def test_gemini_being_over_quota_leaves_the_articles_unread(db, seahawks):
    team, players = seahawks
    item = _pending(db, team, players["Jadarian Price"])
    error = genai_errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}, None)
    gemini = _Gemini(lambda prompt: error)

    report = extract.extract_pending(db, _budget(), client=gemini, now=NOW)

    assert report.calls == 1 and "429" in (report.stopped or "")
    db.refresh(item)
    assert item.status == "pending" and item.attempts == 0


def test_no_call_is_made_once_the_budget_is_used_up(db, seahawks):
    team, players = seahawks
    _pending(db, team, players["Jadarian Price"])
    budget = GeminiBudget("lite", per_minute=100, per_day=1)
    budget.reserve(db, "news")
    gemini = _Gemini(lambda prompt: pytest.fail("Gemini must not be called"))

    report = extract.extract_pending(db, budget, client=gemini, now=NOW)

    assert report.calls == 0 and "budget" in (report.stopped or "")


def test_a_run_makes_no_more_calls_than_its_limit_and_batches_articles(db, seahawks, monkeypatch):
    team, players = seahawks
    price = players["Jadarian Price"]
    for minutes in range(5):
        _pending(db, team, price, minutes=minutes)
    settings = extract.get_settings()
    monkeypatch.setattr(settings, "news_batch_size", 2)
    monkeypatch.setattr(settings, "news_max_calls_per_run", 2)
    gemini = _Gemini(lambda prompt: '{"facts": []}')

    report = extract.extract_pending(db, _budget(), client=gemini, now=NOW)

    assert (report.calls, report.read) == (2, 4)
    assert db.query(NewsItem).filter_by(status="pending").count() == 1


# --- What the projection feed does with it ------------------------------------------------------


def _read(db, team, player, published, **fact):
    item = NewsItem(
        sport="NFL",
        external_id=f"r{player.id}{published.isoformat()}",
        team_id=team.id,
        headline="h",
        description="d",
        published_at=published,
        player_ids=[player.id],
        status="done",
        facts=[
            {
                "player_id": player.id,
                "availability": "out",
                "role": "unclear",
                "about_next_game": True,
                "note": "Out Sunday.",
            }
            | fact
        ],
    )
    db.add(item)
    db.flush()


def _kickoff(db, team, other, start):
    db.add(
        Game(
            sport="NFL",
            season="2026",
            home_team_id=team.id,
            away_team_id=other.id,
            start_time=start,
            status="final",
        )
    )
    db.flush()


@pytest.fixture
def feed():
    # No Sleeper file: only the stored news speaks.
    return Feed(client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))


def test_news_saying_a_player_is_out_for_the_next_game_counts_him_out(
    db, seahawks, feed, monkeypatch
):
    team, players = seahawks
    price = players["Jadarian Price"]
    now = datetime.utcnow()
    other = Team(name="Chargers", abbreviation="LAC", sport="NFL", external_id="nfl:24")
    db.add(other)
    db.flush()
    _kickoff(db, team, other, now - timedelta(days=4))
    _read(db, team, price, now - timedelta(hours=3))

    news = feed.for_teams(db, "NFL", [team.id])

    assert news.out_by_team[team.id] == {price.id}
    assert news.read[price.id]["note"] == "Out Sunday."


def test_news_from_before_the_last_game_or_about_another_game_is_ignored(db, seahawks, feed):
    team, players = seahawks
    now = datetime.utcnow()
    other = Team(name="Chargers", abbreviation="LAC", sport="NFL", external_id="nfl:24")
    db.add(other)
    db.flush()
    _kickoff(db, team, other, now - timedelta(days=2))
    _read(db, team, players["Jadarian Price"], now - timedelta(days=3))  # out for the last game
    _read(db, team, players["Zach Charbonnet"], now - timedelta(hours=1), about_next_game=False)

    news = feed.for_teams(db, "NFL", [team.id])

    assert news.out_by_team == {} and news.read == {}


def test_the_latest_article_about_a_player_wins_and_a_role_alone_does_not_make_him_out(
    db, seahawks, feed
):
    team, players = seahawks
    price = players["Jadarian Price"]
    now = datetime.utcnow()
    _read(db, team, price, now - timedelta(hours=5), availability="out")
    _read(db, team, price, now - timedelta(hours=1), availability="returning", role="starter")

    news = feed.for_teams(db, "NFL", [team.id])

    assert news.out_by_team == {}
    assert news.read[price.id]["role"] == "starter"
