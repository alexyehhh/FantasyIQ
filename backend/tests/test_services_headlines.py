"""Integration tests for app/services/headlines.py (real Postgres, rolled back after)."""

from datetime import datetime

import pytest

from app.db.models import Game, Player, PlayerGameStats, PlayerGameStatsNFL, Team
from app.db.session import SessionLocal
from app.services import headlines as headlines_service


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


def _player(db, team, name, sport="NFL", position="WR", **kwargs):
    player = Player(name=name, sport=sport, team_id=team.id, position=position, **kwargs)
    db.add(player)
    db.flush()
    return player


def _stat_line(db, player, opponent, when, *, week=1, season=None, home=True, **stats):
    season = season or ("2026" if player.sport == "NFL" else "2025-26")
    game = Game(
        sport=player.sport, season=season,
        home_team_id=player.team_id if home else opponent.id,
        away_team_id=opponent.id if home else player.team_id,
        start_time=when, status="final", week=week, home_score=30, away_score=20,
    )
    db.add(game)
    db.flush()
    model = PlayerGameStatsNFL if player.sport == "NFL" else PlayerGameStats
    db.add(model(player_id=player.id, game_id=game.id, **stats))
    db.flush()
    return game


class TestPerformanceHeadlines:
    def test_qb_headline_describes_the_real_stat_line_and_result(self, db):
        team = _team(db, "Mine", "MNE")
        rival = _team(db, "Rival Cardinals", "RIV")
        purdy = _player(db, team, "Brock Purdy", position="QB")
        _stat_line(
            db, purdy, rival, datetime(2026, 9, 27), week=3,
            passing_yards=297, passing_touchdowns=4,
        )

        headlines = headlines_service.get_headlines(db, sport="NFL")

        performance = next(h for h in headlines if h.kind == "performance")
        assert (
            performance.text == "Brock Purdy threw for 297 yards and 4 TDs in a win vs Cardinals."
        )

    def test_rb_headline_adds_receiving_when_notable(self, db):
        team = _team(db, "Mine", "MNE")
        rival = _team(db, "Rival Jets", "RIV")
        gibbs = _player(db, team, "Jahmyr Gibbs", position="RB")
        _stat_line(
            db, gibbs, rival, datetime(2026, 9, 27), week=3,
            rushing_yards=99, rushing_touchdowns=2, receptions=7, receiving_yards=65,
        )

        headlines = headlines_service.get_headlines(db, sport="NFL")

        performance = next(h for h in headlines if h.kind == "performance")
        assert "rushed for 99 yards and 2 TDs" in performance.text
        assert "7 catches for 65 yards" in performance.text

    def test_a_loss_is_phrased_as_a_loss_at_the_opponent_when_on_the_road(self, db):
        team = _team(db, "Mine", "MNE")
        rival = _team(db, "Rival Commanders", "RIV")
        player = _player(db, team, "Jaxon Smith-Njigba", position="WR")
        # away (home=False): the helper's default score (home 30, away 20) is a road loss
        _stat_line(
            db, player, rival, datetime(2026, 9, 27), week=3, home=False,
            receptions=10, receiving_yards=128, receiving_touchdowns=2,
        )

        headlines = headlines_service.get_headlines(db, sport="NFL")

        performance = next(h for h in headlines if h.kind == "performance")
        assert "in a loss at Commanders" in performance.text

    def test_nba_headline_uses_points_rebounds_and_assists(self, db):
        team = _team(db, "Mine", "MNE", sport="NBA")
        rival = _team(db, "Rival", "RIV", sport="NBA")
        player = _player(db, team, "Steph Curry", sport="NBA", position="G")
        _stat_line(db, player, rival, datetime(2026, 1, 5), points=40, rebounds=5, assists=8)

        headlines = headlines_service.get_headlines(db, sport="NBA")

        performance = next(h for h in headlines if h.kind == "performance")
        assert performance.text == (
            "Steph Curry scored 40 points with 5 rebounds and 8 assists in a win vs Rival."
        )


class TestInjuryHeadlines:
    def test_uses_the_real_reported_note_when_the_player_has_a_real_season_role(self, db):
        team = _team(db, "Mine", "MNE")
        rival = _team(db, "Rival", "RIV")
        achane = _player(
            db, team, "De'Von Achane", position="RB",
            injury_status="Injured Reserve", injury_type="Knee - ACL",
            injury_note="The Dolphins placed Achane (knee) on injured reserve Monday.",
            injury_updated_at=datetime(2026, 9, 28, 20, 10),
        )
        _stat_line(db, achane, rival, datetime(2026, 9, 13), week=1, rushing_yards=120)  # 12 pts

        headlines = headlines_service.get_headlines(db, sport="NFL")

        injury = next(h for h in headlines if h.kind == "injury")
        assert injury.text == "The Dolphins placed Achane (knee) on injured reserve Monday."

    def test_excludes_a_player_with_no_real_reported_note(self, db):
        team = _team(db, "Mine", "MNE")
        rival = _team(db, "Rival", "RIV")
        williams = _player(
            db, team, "Caleb Williams", position="QB",
            injury_status="Out", injury_type="Hamstring", injury_note="inactive",
            injury_updated_at=datetime(2026, 9, 28, 22, 49),
        )
        _stat_line(db, williams, rival, datetime(2026, 9, 13), week=1, passing_yards=300)

        headlines = headlines_service.get_headlines(db, sport="NFL")

        assert not any(h.kind == "injury" and h.player.name == "Caleb Williams" for h in headlines)

    def test_excludes_a_player_with_negligible_season_production(self, db):
        """The "one catch, then injured" case: a real note, but no real season role."""
        team = _team(db, "Mine", "MNE")
        rival = _team(db, "Rival", "RIV")
        bench = _player(
            db, team, "Camp Body", position="WR",
            injury_status="Out", injury_type="Knee",
            injury_note="A real, substantive reported note about this depth receiver's injury.",
            injury_updated_at=datetime(2026, 9, 28),
        )
        _stat_line(db, bench, rival, datetime(2026, 9, 13), week=1, receptions=1, receiving_yards=4)

        headlines = headlines_service.get_headlines(db, sport="NFL")

        assert not any(h.kind == "injury" and h.player.name == "Camp Body" for h in headlines)

    def test_excludes_non_skill_positions(self, db):
        team = _team(db, "Mine", "MNE")
        _player(
            db, team, "Bench Safety", position="S", injury_status="Out",
            injury_note="A long real reported note about a safety's injury this week.",
            injury_updated_at=datetime(2026, 9, 28),
        )

        headlines = headlines_service.get_headlines(db, sport="NFL")

        assert not any(h.player.name == "Bench Safety" for h in headlines)

    def test_excludes_kickers(self, db):
        team = _team(db, "Mine", "MNE")
        rival = _team(db, "Rival", "RIV")
        kicker = _player(
            db, team, "Reliable Leg", position="PK", injury_status="Out",
            injury_note="A long real reported note about this kicker's injury this week.",
            injury_updated_at=datetime(2026, 9, 28),
        )
        _stat_line(db, kicker, rival, datetime(2026, 9, 13), week=1, field_goals_made=4)

        headlines = headlines_service.get_headlines(db, sport="NFL")

        assert not any(h.player.name == "Reliable Leg" for h in headlines)

    def test_nba_has_no_position_filter_but_still_needs_a_real_role(self, db):
        team = _team(db, "Mine", "MNE", sport="NBA")
        rival = _team(db, "Rival", "RIV", sport="NBA")
        center = _player(
            db, team, "Big Center", sport="NBA", position="C", injury_status="Out",
            injury_note="A long real reported note about a center's injury this week.",
            injury_updated_at=datetime(2026, 1, 5),
        )
        _stat_line(db, center, rival, datetime(2026, 1, 1), points=20, rebounds=10)

        headlines = headlines_service.get_headlines(db, sport="NBA")

        assert any(h.player.name == "Big Center" for h in headlines)


class TestHeadlineMix:
    def test_alternates_performance_and_injury_and_respects_the_limit(self, db):
        team = _team(db, "Mine", "MNE")
        rival = _team(db, "Rival", "RIV")
        for i in range(3):
            scorer = _player(db, team, f"Scorer {i}", position="WR")
            _stat_line(
                db, scorer, rival, datetime(2026, 9, 25 + i), week=3,
                receptions=5, receiving_yards=80 - i * 10,
            )
        for i in range(3):
            hurt = _player(
                db, team, f"Hurt {i}", position="WR", injury_status="Out",
                injury_note=f"A real, substantive reported note about Hurt {i}'s injury this week.",
                injury_updated_at=datetime(2026, 9, 28, 20 + i),
            )
            _stat_line(
                db, hurt, rival, datetime(2026, 9, 6), week=1, receptions=5, receiving_yards=80,
            )

        headlines = headlines_service.get_headlines(db, sport="NFL", limit=4)

        assert len(headlines) == 4
        assert [h.kind for h in headlines] == ["performance", "injury", "performance", "injury"]

    def test_is_empty_with_nothing_to_report(self, db):
        assert headlines_service.get_headlines(db, sport="NFL") == []
