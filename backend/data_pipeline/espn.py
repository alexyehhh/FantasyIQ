"""Small provider client for ESPN's public site API.

ESPN publishes no rate limit for this API, so the client is deliberately gentle: every request in
the process goes through one `RequestGate` that spaces requests out, and that stops asking for a
while (fail-fast, not sleeping) once ESPN answers 429 or 503, lengthening the pause each time it
happens again.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.core.config import get_settings


class ESPNError(RuntimeError):
    """Raised when ESPN data cannot be fetched or is not JSON."""


class ESPNRateLimited(ESPNError):
    """ESPN told us to slow down, or we are still holding off because it did."""


# Answers that mean "too much, come back later" rather than "this request is wrong".
_BACK_OFF_STATUSES = {429, 503}
_FIRST_PAUSE_SECONDS = 60.0
_MAX_PAUSE_SECONDS = 900.0


class RequestGate:
    """Paces requests and holds them off after ESPN pushes back; safe to share across threads.

    `wait_turn` hands out request slots `min_interval` seconds apart (parallel callers queue for
    their slot rather than bursting). While backed off it raises `ESPNRateLimited` at once instead
    of sleeping, so a caller is never stuck waiting minutes; jobs treat it as a failed attempt and
    try again later."""

    def __init__(
        self,
        min_interval: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self._blocked_until = 0.0
        self._strikes = 0

    def wait_turn(self) -> None:
        with self._lock:
            now = self._clock()
            if now < self._blocked_until:
                raise ESPNRateLimited(
                    f"Holding off ESPN requests for another {self._blocked_until - now:.0f}s"
                )
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._min_interval
        if slot > now:
            self._sleep(slot - now)

    def succeeded(self) -> None:
        with self._lock:
            self._strikes = 0

    def back_off(self, retry_after: float | None = None) -> float:
        """Stop asking for `retry_after` seconds (else 60, doubling per repeat, capped at 15
        minutes); returns the pause."""
        with self._lock:
            self._strikes += 1
            pause = retry_after or _FIRST_PAUSE_SECONDS * 2 ** (self._strikes - 1)
            pause = min(pause, _MAX_PAUSE_SECONDS)
            self._blocked_until = self._clock() + pause
            return pause


_default_gate: RequestGate | None = None
_default_gate_lock = threading.Lock()


def default_gate() -> RequestGate:
    """The one gate every ESPN client in this process shares unless it is given its own."""
    global _default_gate
    with _default_gate_lock:
        if _default_gate is None:
            _default_gate = RequestGate(get_settings().espn_min_request_interval_seconds)
        return _default_gate


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return None  # absent, or an HTTP date, which ESPN doesn't send


class ESPNClient:
    def __init__(
        self,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
        gate: RequestGate | None = None,
    ) -> None:
        self._gate = gate or default_gate()
        self._client = client or httpx.Client(
            base_url="https://site.api.espn.com",
            # No custom User-Agent on purpose: ESPN's edge answers a browser-style (or
            # any invented) UA with 403 Access Denied but serves the default httpx one.
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.espn.com/",
            },
            timeout=timeout,
        )
        self._cdn_client = httpx.Client(
            base_url="https://cdn.espn.com",
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.espn.com/",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()
        self._cdn_client.close()

    def _request(
        self, http: httpx.Client, path: str, params: dict[str, str], failure: str
    ) -> Any:
        """One paced request; the parsed JSON. `failure` is the ESPNError message."""
        self._gate.wait_turn()
        try:
            response = http.get(path, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _BACK_OFF_STATUSES:
                pause = self._gate.back_off(_retry_after(exc.response))
                raise ESPNRateLimited(
                    f"{failure} (ESPN answered {exc.response.status_code}; "
                    f"holding off {pause:.0f}s)"
                ) from exc
            raise ESPNError(failure) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ESPNError(failure) from exc
        self._gate.succeeded()
        return payload

    def get(self, sport: str, league: str, resource: str, **params: str) -> dict[str, Any]:
        payload = self._request(
            self._client,
            f"/apis/site/v2/sports/{sport}/{league}/{resource}",
            params,
            f"ESPN request failed: {sport}/{league}/{resource}",
        )
        if not isinstance(payload, dict):
            raise ESPNError("Unexpected ESPN response")
        return payload

    def scoreboard(self, sport: str, league: str, date: str | None = None) -> dict[str, Any]:
        params = {"dates": date} if date else {}
        return self.get(sport, league, "scoreboard", **params)

    def summary(self, sport: str, league: str, event_id: str) -> dict[str, Any]:
        try:
            return self.get(sport, league, "summary", event=event_id)
        except ESPNRateLimited:
            raise
        except ESPNError:
            return self.cdn_game(league, event_id)

    def cdn_game(self, league: str, event_id: str) -> dict[str, Any]:
        failure = f"ESPN CDN request failed: {league}/game"
        payload = self._request(
            self._cdn_client, f"/core/{league}/game", {"xhr": "1", "gameId": event_id}, failure
        )
        try:
            game_package = payload.get("gamepackageJSON")
            if isinstance(game_package, str):
                game_package = json.loads(game_package)
        except (AttributeError, ValueError, json.JSONDecodeError) as exc:
            raise ESPNError(failure) from exc
        if not isinstance(game_package, dict):
            raise ESPNError("Unexpected ESPN CDN game response")
        return game_package

    def teams(self, sport: str, league: str) -> dict[str, Any]:
        return self.get(sport, league, "teams", limit="100")

    def schedule(
        self, sport: str, league: str, team_id: str, season_type: int = 2
    ) -> dict[str, Any]:
        """A team's full schedule for one season type (2 = regular season).

        Without `seasontype` ESPN returns whichever type is "current", which for
        the NBA in the offseason is preseason.
        """
        return self.get(
            sport, league, f"teams/{team_id}/schedule", seasontype=str(season_type)
        )

    def roster(self, sport: str, league: str, team_id: str) -> dict[str, Any]:
        return self.get(sport, league, f"teams/{team_id}/roster")

    def injuries(self, sport: str, league: str) -> dict[str, Any]:
        return self.get(sport, league, "injuries")

    def news(self, sport: str, league: str) -> dict[str, Any]:
        return self.get(sport, league, "news")
