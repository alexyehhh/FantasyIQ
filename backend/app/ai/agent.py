"""The tool-calling loop: Gemini plus the tools in app/ai/tools.py.

One workflow for v1 (Milestone 9): compare a handful of players/defenses for one lineup spot
and explain who to start. Function calling is run manually (automatic_function_calling
disabled) rather than through the SDK's automatic mode, so every call is logged here before
the model sees the result — Milestone 9's "seed of observability" per AGENTS.md.

The exact SDK shape below (manual Content/Part loop, `parameters_json_schema` for a plain JSON
Schema, function responses sent back with role="user") was checked against the installed
google-genai package's own source rather than assumed, since Google's docs site had partly
moved on to a newer, different (stateful) Interactions API that this code doesn't use.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from sqlalchemy.orm import Session

from app.ai import tools
from app.ai.prompts import SYSTEM_PROMPT
from app.core.config import get_settings

logger = logging.getLogger("app.ai")

# A start/sit comparison needs at most one round per candidate plus a final answer; this is a
# safety cap against a model that keeps calling tools instead of answering.
MAX_ROUNDS = 6


class AgentConfigError(RuntimeError):
    """Gemini isn't configured (no API key)."""


class AgentRoundLimitExceeded(RuntimeError):
    """The model kept calling tools past MAX_ROUNDS without answering."""


class AgentUpstreamError(RuntimeError):
    """Gemini itself failed — overloaded, rate-limited on Google's side, or a bad request."""


@dataclass
class ToolCallLog:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    elapsed_ms: int


@dataclass
class AgentReply:
    text: str
    tool_calls: list[ToolCallLog] = field(default_factory=list)


def _declarations() -> list[types.FunctionDeclaration]:
    return [types.FunctionDeclaration(**spec) for spec in tools.TOOL_DECLARATIONS]


def _client() -> genai.Client:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise AgentConfigError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=settings.gemini_api_key)


def ask(db: Session, message: str, *, client: genai.Client | None = None) -> AgentReply:
    """Answers `message`, calling tools as needed. `client` is injectable for tests; production
    callers omit it and get a real Gemini client built from settings."""
    client = client or _client()
    settings = get_settings()
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[types.Tool(function_declarations=_declarations())],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part.from_text(text=message)])
    ]
    trace: list[ToolCallLog] = []

    for _round in range(MAX_ROUNDS):
        try:
            response = client.models.generate_content(
                model=settings.gemini_model, contents=contents, config=config
            )
        except genai_errors.APIError as exc:
            raise AgentUpstreamError(
                f"Gemini error {exc.code} ({exc.status}): {exc.message}"
            ) from exc
        candidates = response.candidates or []
        if not candidates or candidates[0].content is None:
            return AgentReply(text=response.text or "", tool_calls=trace)
        contents.append(candidates[0].content)
        calls = response.function_calls
        if not calls:
            return AgentReply(text=response.text or "", tool_calls=trace)

        response_parts = []
        for call in calls:
            # A function call from Gemini always names the tool; the fallback only protects
            # against a malformed response, and tools.call_tool already answers an unknown
            # name with a normal {"error": ...} the model can react to.
            name = call.name or "unknown_tool"
            arguments = dict(call.args or {})
            started = time.monotonic()
            result = tools.call_tool(db, name, arguments)
            elapsed_ms = round((time.monotonic() - started) * 1000)
            logger.info(
                "ai_tool_call tool=%s ok=%s elapsed_ms=%d arguments=%s",
                name,
                "error" not in result,
                elapsed_ms,
                arguments,
            )
            trace.append(
                ToolCallLog(name=name, arguments=arguments, result=result, elapsed_ms=elapsed_ms)
            )
            response_parts.append(types.Part.from_function_response(name=name, response=result))
        contents.append(types.Content(role="user", parts=response_parts))

    raise AgentRoundLimitExceeded(f"Exceeded {MAX_ROUNDS} tool-call rounds without an answer")


def start_sit_message(
    candidates: list[dict[str, Any]], *, week: int | None, scoring: str | None
) -> str:
    """The user turn for the one workflow Milestone 9 ships: compare `candidates` (each a
    {"kind", "entity_id"} pair, as the frontend already models a start/sit compare) for one
    lineup spot and recommend who to start."""
    lines = [f"- {c['kind']} id {c['entity_id']}" for c in candidates]
    parts = ["Compare these candidates for one lineup spot and recommend who to start:", *lines]
    if week is not None:
        parts.append(f"NFL week: {week}")
    if scoring:
        parts.append(f"Scoring: {scoring}")
    parts.append(
        "Look up each one's stats, schedule and projection with the tools before answering."
    )
    return "\n".join(parts)
