from fastapi.testclient import TestClient

from app.main import app
from app.services.scoring import ScoringConfig

client = TestClient(app)


def test_the_nfl_preset_carries_weights_and_brackets():
    response = client.get("/api/v1/scoring/presets/NFL")

    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["sport"]) == ("FantasyIQ standard (PPR)", "NFL")
    assert body["player_weights"]["receptions"] == 1
    assert body["field_goal_made"][0] == {"min": 0, "max": 39, "points": 3}
    assert body["field_goal_made"][-1] == {"min": 50, "max": None, "points": 5}
    assert body["defense_weights"]["sacks"] == 1
    assert body["points_allowed"][0] == {"min": 0, "max": 0, "points": 10}


def test_the_preset_round_trips_as_a_valid_scoring_param():
    body = client.get("/api/v1/scoring/presets/NBA").json()

    config = ScoringConfig.model_validate(body)

    assert config.player_weights["rebounds"] == 1.2
    assert not config.field_goal_made


def test_an_unknown_sport_is_rejected():
    assert client.get("/api/v1/scoring/presets/MLB").status_code == 422
