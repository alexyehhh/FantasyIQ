"""API tests for POST /api/v1/analyst/start-sit.

The Gemini call itself is covered by test_ai_agent.py; here `agent.ask` is stubbed so this file
is only about request/response translation and error mapping (app/api/v1/analyst.py)."""

import pytest
from fastapi.testclient import TestClient

from app.ai import agent
from app.ai.agent import AgentReply, ToolCallLog
from app.db.session import SessionLocal, get_db
from app.main import app


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_start_sit_returns_the_explanation_and_tool_trace(client, monkeypatch):
    captured = {}

    def fake_ask(db, message, **kwargs):
        captured["message"] = message
        return AgentReply(
            text="Start Wes Receiver.",
            tool_calls=[
                ToolCallLog(
                    name="get_projection",
                    arguments={"kind": "player", "entity_id": 1},
                    result={"fantasy_points": 18.4},
                    elapsed_ms=12,
                )
            ],
        )

    monkeypatch.setattr(agent, "ask", fake_ask)

    response = client.post(
        "/api/v1/analyst/start-sit",
        json={"candidates": [{"kind": "player", "entity_id": 1}], "week": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["explanation"] == "Start Wes Receiver."
    assert body["tool_calls"] == [
        {
            "name": "get_projection",
            "arguments": {"kind": "player", "entity_id": 1},
            "result": {"fantasy_points": 18.4},
        }
    ]
    assert "- player id 1" in captured["message"]
    assert "NFL week: 3" in captured["message"]


def test_start_sit_needs_at_least_one_candidate(client):
    response = client.post("/api/v1/analyst/start-sit", json={"candidates": []})
    assert response.status_code == 422


def test_start_sit_503s_when_gemini_is_not_configured(client, monkeypatch):
    def fake_ask(db, message, **kwargs):
        raise agent.AgentConfigError("GEMINI_API_KEY is not set")

    monkeypatch.setattr(agent, "ask", fake_ask)

    response = client.post(
        "/api/v1/analyst/start-sit", json={"candidates": [{"kind": "player", "entity_id": 1}]}
    )
    assert response.status_code == 503


def test_start_sit_502s_when_the_model_never_answers(client, monkeypatch):
    def fake_ask(db, message, **kwargs):
        raise agent.AgentRoundLimitExceeded("Exceeded 6 tool-call rounds without an answer")

    monkeypatch.setattr(agent, "ask", fake_ask)

    response = client.post(
        "/api/v1/analyst/start-sit", json={"candidates": [{"kind": "player", "entity_id": 1}]}
    )
    assert response.status_code == 502
