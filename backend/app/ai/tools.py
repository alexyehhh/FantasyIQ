"""Tools the AI Analyst can call.

Each one is a thin wrapper around an existing app/services function (AGENTS.md #2: single
source of business logic — the tool layer only reshapes an answer for the model, never
recomputes it). A tool never raises: whatever goes wrong comes back as {"error": "..."}, since
the agent loop always needs something to hand back to the model to keep the conversation going.

`get_matchup` deliberately returns schedule facts only. Milestone 8 (opponent-strength) hasn't
been built, so there is no difficulty rating to give here yet.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.db.models import Player, Team
from app.services import defenses as defenses_service
from app.services import players as players_service
from app.services import season_summary
from app.services.projections import service as projections_service
from app.services.projections.base import ProjectionError, UnknownSource
from app.services.projections.service import ProjectionInputError
from app.services.scoring import resolve_scoring

Kind = Literal["player", "defense"]

# How many recent games get_stats includes; the point of the tool is "what's going on lately",
# not a full log (the model can ask get_projection for what's expected next).
_RECENT_GAMES = 5


def _entity(db: Session, kind: Kind, entity_id: int) -> Player | Team | None:
    if kind == "player":
        return players_service.get_player(db, entity_id)
    return defenses_service.get_defense(db, entity_id)


def _season_summary_dict(summary: season_summary.SeasonSummary | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    return {
        "season": summary.season,
        "games_played": summary.games,
        "position_group": summary.position_group,
        "pool_size": summary.pool_size,
        "stats": {
            stat: {"total": ranked.total, "rank": ranked.rank, "tied": ranked.tied}
            for stat, ranked in summary.stats.items()
        },
    }


def get_stats(db: Session, *, kind: Kind, entity_id: int) -> dict[str, Any]:
    """A player's or NFL defense's identity, current-season totals with rank, and recent games."""
    entity = _entity(db, kind, entity_id)
    if entity is None:
        return {"error": f"No {kind} with id {entity_id}"}

    if isinstance(entity, Player):
        sport = entity.sport
        config = resolve_scoring(None, sport)
        summary = season_summary.get_player_season_summary(db, entity, config)
        player_log = players_service.get_player_game_log(db, entity, limit=_RECENT_GAMES)
        recent = [
            {
                "date": row.game.start_time.date().isoformat(),
                "opponent": row.opponent.abbreviation if row.opponent else None,
                "is_home": row.is_home,
                "status": row.game.status,
                "result": row.result,
                "fantasy_points": round(players_service.game_fantasy_points(config, row), 1),
            }
            for row in player_log
        ]
        identity: dict[str, Any] = {
            "id": entity.id,
            "kind": "player",
            "name": entity.name,
            "sport": sport,
            "position": entity.position,
            "team": entity.team.abbreviation if entity.team else None,
            "active": entity.active,
            "injury_status": entity.injury_status,
        }
    else:
        config = resolve_scoring(None, "NFL")
        summary = season_summary.get_defense_season_summary(db, entity, config)
        defense_log = defenses_service.get_defense_game_log(db, entity, limit=_RECENT_GAMES)
        recent = [
            {
                "date": row.game.start_time.date().isoformat(),
                "opponent": row.opponent.abbreviation if row.opponent else None,
                "is_home": row.is_home,
                "status": row.game.status,
                "result": row.result,
                "fantasy_points": round(
                    defenses_service.defense_game_fantasy_points(config, row), 1
                ),
            }
            for row in defense_log
        ]
        identity = {
            "id": entity.id,
            "kind": "defense",
            "name": f"{entity.name} D/ST",
            "sport": "NFL",
            "position": "DEF",
            "team": entity.abbreviation,
            "active": True,
            "injury_status": None,
        }

    return {
        **identity,
        "scoring": "default",
        "season_summary": _season_summary_dict(summary),
        "recent_games": recent,
    }


def get_matchup(
    db: Session, *, kind: Kind, entity_id: int, week: int | None = None
) -> dict[str, Any]:
    """The team's schedule around a game: opponent, home/away, date, result if played.

    Schedule only, on purpose — there is no opponent-strength rating to give yet."""
    entity = _entity(db, kind, entity_id)
    if entity is None:
        return {"error": f"No {kind} with id {entity_id}"}
    team = entity.team if isinstance(entity, Player) else entity
    if team is None:
        return {"note": "This player has no current team on record."}

    schedule = players_service.get_team_schedule(db, team.id, team.sport)
    if week is not None:
        if team.sport != "NFL":
            return {"error": "week only applies to the NFL"}
        schedule = [m for m in schedule if m.game.week == week]
    else:
        # Just what's next, not the whole season — the model can ask again for a later week.
        upcoming = [m for m in schedule if m.game.status != "final"]
        schedule = upcoming[:1] or schedule[-1:]

    return {
        "team": team.abbreviation,
        "bye_week": team.bye_week if team.sport == "NFL" else None,
        "games": [
            {
                "week": matchup.game.week,
                "date": matchup.game.start_time.date().isoformat(),
                "opponent": matchup.opponent.abbreviation if matchup.opponent else None,
                "is_home": matchup.is_home,
                "status": matchup.game.status,
                "result": matchup.result,
            }
            for matchup in schedule
        ],
        "note": "Schedule only; FantasyIQ doesn't rate matchup difficulty yet.",
    }


def get_projection(
    db: Session,
    *,
    kind: Kind,
    entity_id: int,
    source: str = "sleeper",
    scoring: str | None = None,
    week: int | None = None,
) -> dict[str, Any]:
    """The expected stat line and fantasy points for a player's or defense's next game (or a
    given NFL week), from a named projection source, scored under `scoring`."""
    entity = _entity(db, kind, entity_id)
    if entity is None:
        return {"error": f"No {kind} with id {entity_id}"}
    sport = entity.sport if isinstance(entity, Player) else "NFL"
    try:
        config = resolve_scoring(scoring, sport)
        results = projections_service.project(
            db,
            sport=sport,
            source=source,
            config=config,
            player_ids=[entity_id] if kind == "player" else (),
            defense_ids=[entity_id] if kind == "defense" else (),
            week=week,
        )
    except (UnknownSource, ProjectionInputError, ValueError) as exc:
        return {"error": str(exc)}
    except ProjectionError as exc:
        return {"error": f"{source} could not be reached: {exc}"}
    if not results:
        return {"error": "No projection returned"}

    projection = results[0]
    return {
        "source": source,
        "status": projection.status,
        "fantasy_points": projection.fantasy_points,
        "low": projection.low,
        "high": projection.high,
        "opponent": projection.opponent.abbreviation if projection.opponent else None,
        "is_home": projection.is_home,
        "stats": projection.stats,
        "unprojected_stats": projection.unprojected,
        "notes": projection.notes,
        "injury_status": projection.injury_status,
    }


TOOL_SPECS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_stats": get_stats,
    "get_matchup": get_matchup,
    "get_projection": get_projection,
}

_ENTITY_KIND_SCHEMA = {
    "type": "string",
    "enum": ["player", "defense"],
    "description": (
        '"player" for anyone at a skill position, "defense" for an NFL team defense/special '
        "teams unit (there is no defense in the NBA)."
    ),
}
_ENTITY_ID_SCHEMA = {"type": "integer", "description": "The FantasyIQ player or team id."}
_WEEK_SCHEMA = {"type": "integer", "description": "NFL week (1-18); omit for the next game."}

TOOL_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "get_stats",
        "description": (
            "A player's or NFL defense's identity, current-season totals with their rank among "
            "others at the position, and their last few games played."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {"kind": _ENTITY_KIND_SCHEMA, "entity_id": _ENTITY_ID_SCHEMA},
            "required": ["kind", "entity_id"],
        },
    },
    {
        "name": "get_matchup",
        "description": (
            "The team's schedule around a game: opponent, home/away, date, result if already "
            "played. This is schedule information only — it does not rate how tough the "
            "opponent is; FantasyIQ has no matchup-difficulty model yet."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "kind": _ENTITY_KIND_SCHEMA,
                "entity_id": _ENTITY_ID_SCHEMA,
                "week": _WEEK_SCHEMA,
            },
            "required": ["kind", "entity_id"],
        },
    },
    {
        "name": "get_projection",
        "description": (
            "The expected stat line and fantasy points for a player's or defense's next game "
            "(or a given NFL week), from a named projection source."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "kind": _ENTITY_KIND_SCHEMA,
                "entity_id": _ENTITY_ID_SCHEMA,
                "source": {
                    "type": "string",
                    "description": '"sleeper" is the only projection source available today.',
                },
                "scoring": {
                    "type": "string",
                    "description": (
                        '"default" for FantasyIQ scoring, or an inline JSON ScoringConfig; '
                        "omit for the FantasyIQ default."
                    ),
                },
                "week": _WEEK_SCHEMA,
            },
            "required": ["kind", "entity_id"],
        },
    },
]


def call_tool(db: Session, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Runs a tool by name. Never raises: an unknown tool or bad arguments come back as an
    {"error": ...} dict too, since the model needs something to continue the conversation with."""
    func = TOOL_SPECS.get(name)
    if func is None:
        return {"error": f"Unknown tool {name!r}"}
    try:
        return func(db, **arguments)
    except TypeError as exc:
        return {"error": f"Bad arguments for {name}: {exc}"}
