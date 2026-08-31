"""Small provider client for ESPN's public site API."""

from __future__ import annotations

import json
from typing import Any

import httpx


class ESPNError(RuntimeError):
    """Raised when ESPN data cannot be fetched or is not JSON."""


class ESPNClient:
    def __init__(self, timeout: float = 20.0, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            base_url="https://site.api.espn.com",
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.espn.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
                ),
            },
            timeout=timeout,
        )
        self._cdn_client = httpx.Client(
            base_url="https://cdn.espn.com",
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.espn.com/",
                "User-Agent": self._client.headers.get("User-Agent", "FantasyIQ/0.1"),
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()
        self._cdn_client.close()

    def get(self, sport: str, league: str, resource: str, **params: str) -> dict[str, Any]:
        try:
            response = self._client.get(
                f"/apis/site/v2/sports/{sport}/{league}/{resource}", params=params
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ESPNError(f"ESPN request failed: {sport}/{league}/{resource}") from exc
        if not isinstance(payload, dict):
            raise ESPNError("Unexpected ESPN response")
        return payload

    def scoreboard(self, sport: str, league: str, date: str | None = None) -> dict[str, Any]:
        params = {"dates": date} if date else {}
        return self.get(sport, league, "scoreboard", **params)

    def summary(self, sport: str, league: str, event_id: str) -> dict[str, Any]:
        try:
            return self.get(sport, league, "summary", event=event_id)
        except ESPNError:
            return self.cdn_game(league, event_id)

    def cdn_game(self, league: str, event_id: str) -> dict[str, Any]:
        try:
            response = self._cdn_client.get(
                f"/core/{league}/game", params={"xhr": "1", "gameId": event_id}
            )
            response.raise_for_status()
            payload = response.json()
            game_package = payload.get("gamepackageJSON")
            if isinstance(game_package, str):
                game_package = json.loads(game_package)
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            raise ESPNError(f"ESPN CDN request failed: {league}/game") from exc
        if not isinstance(game_package, dict):
            raise ESPNError("Unexpected ESPN CDN game response")
        return game_package

    def roster(self, sport: str, league: str, team_id: str) -> dict[str, Any]:
        return self.get(sport, league, f"teams/{team_id}/roster")

    def injuries(self, sport: str, league: str) -> dict[str, Any]:
        return self.get(sport, league, "injuries")

    def news(self, sport: str, league: str) -> dict[str, Any]:
        return self.get(sport, league, "news")
