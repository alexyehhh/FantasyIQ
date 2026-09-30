"""Who on a player's team is missing, and how much work that frees up.

A player's own recent games can't say that the starter ahead of him just went down. So every
player-game also gets teammate features: the *vacated* workload, meaning the usual load (rushing
attempts, targets, minutes, ...) of teammates who were active in the team's last few games but are
missing from this one, and the *returning* workload of teammates back after missing the last game,
which takes work away again.

A teammate's usual load is the decaying average of his stats through the last game he played.
Only games of the same season count (rosters turn over between seasons), and only the team's last
`WINDOW` games: a player out longer than that is already in his teammates' recent averages.

Training knows who missed a game from its box score. Projecting a game that hasn't been played, the
missing are the teammates listed out (or doubtful) right now, through the same `Timeline`, so the
two ends of the model see the same kind of number. Box scores record no team per game, so a
player's team is his current one; a traded player's earlier games carry no team context.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.ml.features import DECAY, POSITION_GROUPS, context_columns, context_stats

WINDOW = 6
# The stat that orders a position group by workload, for who is the next man up.
GROUP_LOAD = {
    "QB": "passing_attempts",
    "RB": "rushing_attempts",
    "WR": "receiving_targets",
    "TE": "receiving_targets",
    "G": "minutes",
    "F": "minutes",
    "C": "minutes",
}
# Listed like this (lowercase), a player is expected to miss the game. Day-to-day and questionable
# players mostly play, so they count as present.
EXPECTED_OUT = {"out", "injured reserve", "ir", "suspended", "suspension", "doubtful"}


@dataclass
class _TeamGame:
    game_id: int
    season: str
    members: dict[int, np.ndarray]  # player id -> his usual load after this game


class Timeline:
    """Each team's schedule of finished games and who played in each."""

    def __init__(self, history: pd.DataFrame, team_games: pd.DataFrame, stats: Sequence[str]):
        self.stats = context_stats(stats)
        self.group = {
            int(p): POSITION_GROUPS.get(pos, "")
            for p, pos in history.drop_duplicates("player_id")[
                ["player_id", "position"]
            ].itertuples(index=False)
        }
        played = history.dropna(subset=["team_id"])
        usual = (
            played.groupby("player_id", sort=False)[self.stats]
            .transform(lambda x: x.ewm(alpha=1 - DECAY).mean())
            .to_numpy()
        )
        members: dict[tuple[int, int], dict[int, np.ndarray]] = {}
        for team, game, player, load in zip(
            played["team_id"].astype(int),
            played["game_id"].astype(int),
            played["player_id"].astype(int),
            usual,
            strict=True,
        ):
            members.setdefault((team, game), {})[player] = load
        self.teams: dict[int, list[_TeamGame]] = {}
        self._starts: dict[int, list[pd.Timestamp]] = {}
        for team, game, season, start in zip(
            team_games["team_id"],
            team_games["game_id"],
            team_games["season"],
            team_games["start_time"],
            strict=True,
        ):
            self.teams.setdefault(int(team), []).append(
                _TeamGame(int(game), season, members.get((int(team), int(game)), {}))
            )
            self._starts.setdefault(int(team), []).append(start)

    def position_before(self, team_id: int, start: pd.Timestamp) -> int:
        """How many of the team's games came before `start`."""
        return bisect_left(self._starts.get(team_id, []), start)

    def _recent(self, team_id: int, season: str, k: int) -> list[_TeamGame]:
        games = self.teams.get(team_id, [])
        window = []
        for i in range(k - 1, max(k - 1 - WINDOW, -1), -1):
            if games[i].season != season:
                break
            window.append(games[i])
        return window[::-1]

    def context(
        self, team_id: int, season: str, k: int, out_ids: Collection[int] | None = None
    ) -> tuple[dict[int, np.ndarray], set[int], set[int], set[int]]:
        """(usual load of each recent teammate, those missing, those returning, those newly
        missing: they played the team's last game) for the team's k-th game. The missing are those
        absent from that game's box score or, with `out_ids` (for a game yet to be played), those
        among them."""
        window = self._recent(team_id, season, k)
        if not window:
            return {}, set(), set(), set()
        recent: dict[int, np.ndarray] = {}
        for game in window:
            recent.update(game.members)  # later games overwrite: his load as he last played
        if out_ids is None:
            present = self.teams[team_id][k].members
            missing = {q for q in recent if q not in present}
        else:
            missing = {q for q in recent if q in out_ids}
        returning = {q for q in recent if q not in window[-1].members and q not in missing}
        return recent, missing, returning, {q for q in missing if q in window[-1].members}

    def _inherited(
        self, player_id: int, recent: dict[int, np.ndarray], missing: set[int], gone: set[int]
    ) -> np.ndarray:
        """The share of the missing same-position teammates' load this player can expect to take
        on: what `gone` of them carried, times his part of what the players still there carry. A
        backup with 6 carries behind a starter with 15 and no one else picks up most of the 15.
        `missing` are everyone out, so they don't count as still there."""
        mine = recent.get(player_id)
        group = self.group.get(player_id)
        if mine is None or not group:
            return np.zeros(len(self.stats))
        taken = sum((recent[q] for q in gone if self.group.get(q) == group), np.zeros_like(mine))
        here = mine + sum(
            (v for q, v in recent.items() if q != player_id and q not in missing
             and self.group.get(q) == group),
            np.zeros_like(mine),
        )  # fmt: skip
        return taken * np.divide(mine, here, out=np.zeros_like(mine), where=here > 0)

    def _rank(
        self,
        player_id: int,
        recent: dict[int, np.ndarray],
        missing: set[int],
        depth: Mapping[int, int] | None,
    ) -> float:
        """Where the player stands in his position group among those not out: 1 is the first
        choice, capped at 4. Ranked by the depth chart when it lists him (`depth`: player id ->
        depth chart order), else by recent workload, which is how training sees it. Empty when he
        hasn't played lately."""
        group = self.group.get(player_id)
        if not group or player_id not in recent:
            return float("nan")
        mates = [
            q for q in recent if q != player_id and q not in missing and self.group.get(q) == group
        ]
        if depth and player_id in depth:
            ahead = sum(1 for q in mates if q in depth and depth[q] < depth[player_id])
        else:
            load = self.stats.index(GROUP_LOAD[group])
            ahead = sum(1 for q in mates if recent[q][load] > recent[player_id][load])
        return float(min(ahead + 1, 4))

    def features_for(
        self,
        player_id: int,
        team_id: int,
        season: str,
        k: int,
        out_ids: Collection[int] | None = None,
        depth: Mapping[int, int] | None = None,
    ) -> dict[str, float]:
        """The teammate features for one player in the team's k-th game. `depth` is the depth
        chart order of players, used in place of recent workload to say who is next in line."""
        recent, missing, returning, new = self.context(team_id, season, k, out_ids)
        zero = np.zeros(len(self.stats))
        missing = missing - {player_id}
        vacated = sum((recent[q] for q in missing), zero)
        back = sum((recent[q] for q in returning if q != player_id), zero)
        row = {f"vac__{s}": float(v) for s, v in zip(self.stats, vacated, strict=True)}
        rank = self._rank(player_id, recent, missing, depth)
        for prefix, gone in (("inherit", missing), ("new_inherit", new - {player_id})):
            inherited = self._inherited(player_id, recent, missing, gone)
            row |= {f"{prefix}__{s}": float(v) for s, v in zip(self.stats, inherited, strict=True)}
            if prefix == "new_inherit":  # the first choice is the one who really picks it up
                first = inherited if rank == 1 else np.zeros_like(inherited)
                row |= {
                    f"top_new_inherit__{s}": float(v)
                    for s, v in zip(self.stats, first, strict=True)
                }
        row["group_rank"] = rank
        row |= {f"ret__{s}": float(v) for s, v in zip(self.stats, back, strict=True)}
        row["n_absent"] = float(len(missing))
        row["n_returning"] = float(len(returning - {player_id}))
        return row


def attach_training_context(history: pd.DataFrame, timeline: Timeline, stats: Sequence[str]):
    """`history` with the teammate features of every row, from who actually played each game."""
    index_of = {
        team: {g.game_id: i for i, g in enumerate(games)} for team, games in timeline.teams.items()
    }
    rows = []
    for player, team, game, season in zip(
        history["player_id"], history["team_id"], history["game_id"], history["season"], strict=True
    ):
        k = index_of.get(team, {}).get(game) if pd.notna(team) else None
        rows.append(
            timeline.features_for(int(player), int(team), season, k) if k is not None else {}
        )
    extra = pd.DataFrame(rows, index=history.index, columns=context_columns(stats))
    return pd.concat([history, extra], axis=1)
