"""Save ESPN's player news, for Gemini to read (app/services/news/extract.py).

ESPN's news endpoint can't be paged or asked about one player, and the league-wide feed covers only
the last few hours, so each team's own feed is read instead (50 articles, about two weeks). That is
one request per team through the shared ESPN gate. An article is saved once, keyed by ESPN's id,
however many team feeds carry it. Only the players ESPN tagged on it that we have are kept, and an
article with none (rankings, TV schedules) is saved as skipped so it never costs a Gemini call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import NewsItem, Player, Team
from data_pipeline.espn import ESPNClient, ESPNError, ESPNRateLimited
from data_pipeline.espn_directory import LEAGUES

logger = logging.getLogger(__name__)


@dataclass
class NewsReport:
    teams: int = 0
    saved: int = 0
    errors: list[str] | None = None

    def summary(self) -> str:
        return f"{self.saved} new articles from {self.teams} teams, {len(self.errors or [])} errors"


def _published(raw: dict[str, Any]) -> datetime | None:
    value = raw.get("published") or raw.get("lastModified")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Stored naive UTC, the form the database uses.
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def tagged_athlete_ids(raw: dict[str, Any]) -> list[str]:
    """ESPN's ids of the athletes tagged on an article, in order and without repeats."""
    ids: list[str] = []
    for category in raw.get("categories") or []:
        if not isinstance(category, dict) or category.get("type") != "athlete":
            continue
        athlete_id = category.get("athleteId") or (category.get("athlete") or {}).get("id")
        if athlete_id is not None and str(athlete_id) not in ids:
            ids.append(str(athlete_id))
    return ids


def save_articles(
    db: Session,
    sport: str,
    team: Team,
    articles: list[dict[str, Any]],
    players_by_external_id: dict[str, int],
    *,
    now: datetime,
    max_age: timedelta,
) -> int:
    """Store the articles not seen before; returns how many were new."""
    ids = [str(a["id"]) for a in articles if isinstance(a, dict) and a.get("id") is not None]
    known = set(db.scalars(select(NewsItem.external_id).where(NewsItem.external_id.in_(ids))))
    saved = 0
    for raw in articles:
        if not isinstance(raw, dict) or raw.get("id") is None or str(raw["id"]) in known:
            continue
        published = _published(raw)
        headline = (raw.get("headline") or "").strip()
        if published is None or not headline:
            continue
        known.add(str(raw["id"]))
        player_ids = [
            players_by_external_id[a]
            for a in tagged_athlete_ids(raw)
            if a in players_by_external_id
        ]
        stale = now - published > max_age
        db.add(
            NewsItem(
                sport=sport,
                source="espn",
                external_id=str(raw["id"]),
                team_id=team.id,
                headline=headline[:500],
                description=(raw.get("description") or "").strip()[:2000],
                published_at=published,
                player_ids=player_ids,
                status="skipped" if stale or not player_ids else "pending",
            )
        )
        saved += 1
    db.flush()
    return saved


def refresh_news(
    db: Session,
    client: ESPNClient,
    sport: str,
    *,
    now: datetime | None = None,
    max_age: timedelta = timedelta(days=7),
) -> NewsReport:
    """Read every team's news feed and save the new articles. A team whose feed fails is noted and
    the others carry on; if ESPN says to slow down, the rest are left for the next run."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    espn_sport, espn_league = LEAGUES[sport]
    players = {
        external_id: player_id
        for external_id, player_id in db.execute(
            select(Player.external_id, Player.id).where(Player.sport == sport)
        )
        if external_id
    }
    report = NewsReport(errors=[])
    for team in db.scalars(select(Team).where(Team.sport == sport).order_by(Team.id)):
        if not team.external_id or ":" not in team.external_id:
            continue
        espn_team_id = team.external_id.split(":", 1)[1]
        try:
            payload = client.news(espn_sport, espn_league, espn_team_id)
        except ESPNRateLimited as exc:
            report.errors.append(str(exc))
            break
        except ESPNError as exc:
            report.errors.append(f"{team.abbreviation}: {exc}")
            continue
        articles = payload.get("articles")
        if not isinstance(articles, list):
            report.errors.append(f"{team.abbreviation}: news came back in an unexpected shape")
            continue
        report.teams += 1
        report.saved += save_articles(db, sport, team, articles, players, now=now, max_age=max_age)
    return report
