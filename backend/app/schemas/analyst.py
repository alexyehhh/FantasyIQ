"""Request/response schemas for the AI Analyst API (app/api/v1/analyst.py)."""

from typing import Literal

from pydantic import BaseModel, Field


class Candidate(BaseModel):
    kind: Literal["player", "defense"]
    entity_id: int


class StartSitRequest(BaseModel):
    candidates: list[Candidate] = Field(min_length=1, max_length=6)
    week: int | None = Field(default=None, ge=1, le=18)
    scoring: str | None = None


class ToolCall(BaseModel):
    """One tool call the analyst made while answering, and what it got back."""

    name: str
    arguments: dict
    result: dict


class StartSitResponse(BaseModel):
    explanation: str
    tool_calls: list[ToolCall]
