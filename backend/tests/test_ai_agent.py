"""Unit tests for app/ai/agent.py's tool-calling loop.

The Gemini client is faked (built from the real google.genai.types, so the shapes match what
the SDK actually returns) rather than hitting the network; app/ai/tools.py is stubbed too, since
this file is about the loop's control flow, not what any one tool does (see test_ai_tools.py
for those)."""

import pytest
from google.genai import errors as genai_errors
from google.genai import types

from app.ai import agent


def _response(function_calls=None, text=None):
    if function_calls:
        parts = [
            types.Part.from_function_call(name=name, args=args) for name, args in function_calls
        ]
    else:
        parts = [types.Part.from_text(text=text or "")]
    content = types.Content(role="model", parts=parts)
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


class _FakeModels:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _FakeClient:
    def __init__(self, responses):
        self.models = _FakeModels(responses)


def test_ask_returns_text_when_the_model_answers_immediately():
    client = _FakeClient([_response(text="Start Wes Receiver.")])

    reply = agent.ask(None, "Who should I start?", client=client)

    assert reply.text == "Start Wes Receiver."
    assert reply.tool_calls == []
    assert len(client.models.calls) == 1


def test_ask_calls_tools_and_feeds_the_result_back(monkeypatch):
    calls = []

    def fake_call_tool(db, name, arguments):
        calls.append((name, arguments))
        return {"fantasy_points": 18.4}

    monkeypatch.setattr(agent.tools, "call_tool", fake_call_tool)
    client = _FakeClient(
        [
            _response(function_calls=[("get_projection", {"kind": "player", "entity_id": 1})]),
            _response(text="Start them, they're projected for 18.4."),
        ]
    )

    reply = agent.ask(None, "Who should I start?", client=client)

    assert reply.text == "Start them, they're projected for 18.4."
    assert calls == [("get_projection", {"kind": "player", "entity_id": 1})]
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0].result == {"fantasy_points": 18.4}
    assert reply.tool_calls[0].elapsed_ms >= 0
    # Round 2's request carries the function call and its response back to the model.
    assert len(client.models.calls) == 2
    assert len(client.models.calls[1]["contents"]) == 3


def test_ask_stops_after_the_round_limit(monkeypatch):
    monkeypatch.setattr(agent.tools, "call_tool", lambda db, name, arguments: {"ok": True})
    monkeypatch.setattr(agent, "MAX_ROUNDS", 2)
    always_calls = [
        _response(function_calls=[("get_stats", {"kind": "player", "entity_id": 1})])
        for _ in range(5)
    ]
    client = _FakeClient(always_calls)

    with pytest.raises(agent.AgentRoundLimitExceeded):
        agent.ask(None, "Who should I start?", client=client)


def test_ask_wraps_a_gemini_api_error():
    upstream = genai_errors.ServerError(
        503, {"error": {"code": 503, "message": "High demand", "status": "UNAVAILABLE"}}
    )
    client = _FakeClient([upstream])

    with pytest.raises(agent.AgentUpstreamError):
        agent.ask(None, "Who should I start?", client=client)


def test_ask_without_a_client_needs_an_api_key(monkeypatch):
    monkeypatch.setattr(agent, "get_settings", lambda: type("S", (), {"gemini_api_key": None})())

    with pytest.raises(agent.AgentConfigError):
        agent.ask(None, "Who should I start?")


def test_start_sit_message_lists_every_candidate():
    message = agent.start_sit_message(
        [{"kind": "player", "entity_id": 1}, {"kind": "defense", "entity_id": 5}],
        week=3,
        scoring="default",
    )

    assert "- player id 1" in message
    assert "- defense id 5" in message
    assert "NFL week: 3" in message
    assert "Scoring: default" in message


def test_start_sit_message_omits_absent_fields():
    message = agent.start_sit_message([{"kind": "player", "entity_id": 1}], week=None, scoring=None)

    assert "week" not in message.lower()
    assert "scoring" not in message.lower()
