"""
Seed script: inserts a handful of fake NBA teams/players/games/stats.

Run with: python scripts/seed.py (from backend/, with the venv active
and DB env vars set). This exists purely to manually sanity-check the
schema end-to-end before Milestone 3 brings in real ingestion — it is
NOT how production data gets in.

Safe to re-run: clears its own seeded rows first rather than
duplicating them.
"""

from datetime import datetime, timezone

from app.db.models import Game, Player, PlayerGameStats, Team
from app.db.session import SessionLocal


def seed() -> None:
    db = SessionLocal()
    try:
        # Clear previous seed data (children first, respecting FKs)
        db.query(PlayerGameStats).delete()
        db.query(Game).delete()
        db.query(Player).delete()
        db.query(Team).delete()
        db.commit()

        warriors = Team(name="Golden State Warriors", abbreviation="GSW", sport="NBA")
        lakers = Team(name="Los Angeles Lakers", abbreviation="LAL", sport="NBA")
        db.add_all([warriors, lakers])
        db.flush()  # populate .id without a full commit

        curry = Player(
            name="Stephen Curry",
            sport="NBA",
            team_id=warriors.id,
            position="PG",
            jersey_number=30,
        )
        james = Player(
            name="LeBron James",
            sport="NBA",
            team_id=lakers.id,
            position="SF",
            jersey_number=23,
        )
        db.add_all([curry, james])
        db.flush()

        game = Game(
            sport="NBA",
            season="2025-26",
            home_team_id=warriors.id,
            away_team_id=lakers.id,
            start_time=datetime(2026, 1, 15, 22, 0, tzinfo=timezone.utc),
            status="final",
        )
        db.add(game)
        db.flush()

        db.add_all(
            [
                PlayerGameStats(
                    player_id=curry.id,
                    game_id=game.id,
                    minutes=34.5,
                    points=28,
                    rebounds=5,
                    assists=6,
                    steals=1,
                    blocks=0,
                    turnovers=2,
                    field_goal_attempts=19,
                    three_point_attempts=11,
                ),
                PlayerGameStats(
                    player_id=james.id,
                    game_id=game.id,
                    minutes=36.0,
                    points=25,
                    rebounds=8,
                    assists=9,
                    steals=1,
                    blocks=1,
                    turnovers=3,
                    field_goal_attempts=17,
                    three_point_attempts=4,
                ),
            ]
        )
        db.commit()
        print(f"Seeded {db.query(Team).count()} teams, "
              f"{db.query(Player).count()} players, "
              f"{db.query(Game).count()} games, "
              f"{db.query(PlayerGameStats).count()} stat lines.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
