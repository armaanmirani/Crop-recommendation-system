import math
import numpy as np
import pytest
import app as module

SAMPLE = {"N": 90, "P": 42, "K": 43, "temperature": 20.9, "humidity": 82, "ph": 6.5, "rainfall": 203}

@pytest.fixture
def client():
    module.app.config["TESTING"] = True
    return module.app.test_client()

def test_page_and_models(client):
    assert client.get("/").status_code == 200
    assert client.get("/api/health").json["models"] == ["random_forest", "xgboost"]
    data = client.get("/api/metadata").json
    assert data["samples"] == 2200 and len(data["crops"]) == 22
    assert data["split"]["test"] == 440
    for metrics in data["metrics"].values():
        assert metrics["accuracy"] > .90
        assert sum(map(sum, metrics["confusion_matrix"])) == 440

@pytest.mark.parametrize("model", ["random_forest", "xgboost"])
def test_rice_inference(client, model):
    response = client.post("/api/recommend", json={**SAMPLE, "model": model})
    assert response.status_code == 200
    result = response.json
    assert result["recommendations"][0]["crop"] == "rice"
    assert result["recommendations"][0]["water_caution"]
    assert set(result["comparison"]) == {"random_forest", "xgboost"}
    assert not result["market_ranking_applied"]

@pytest.mark.parametrize("patch", [{"ph": -1}, {"ph": 15}, {"N": True}, {"N": None}, {"humidity": 101},
    {"temperature": "nan"}, {"N": math.inf}, {"model": []}, {"water_availability": []},
    {"market_weight": 2}, {"market": []}, {"market": {"unknown": {}}}, {"area_hectares": 0},
    {"market": {"rice": {"price_per_kg": 30}}}])
def test_invalid_requests(client, patch):
    result = client.post("/api/recommend", json={**SAMPLE, **patch})
    assert result.status_code == 400
    assert "error" in result.json

def test_malformed_and_missing_fields(client):
    assert client.post("/api/recommend", data="{", content_type="application/json").status_code == 400
    assert client.post("/api/recommend", json={}).status_code == 400
    assert client.post("/api/recommend", json=[]).status_code == 400

def test_out_of_distribution_warning(client):
    result = client.post("/api/recommend", json={**SAMPLE, "temperature": 55}).json
    assert any("temperature is outside" in warning for warning in result["warnings"])

def test_profit_formula(client):
    result = client.post("/api/recommend", json={**SAMPLE, "area_hectares": 2, "market": {
        "rice": {"price_per_kg": 30, "yield_kg_per_hectare": 4000, "cost_per_hectare": 50000}}}).json
    assert result["recommendations"][0]["market"]["estimated_profit"] == 140000

@pytest.fixture
def ambiguous_models(monkeypatch):
    real = module.bundle()
    probabilities = np.zeros(len(real["encoder"].classes_))
    for crop, score in [("rice", .6), ("jute", .39), ("apple", .01)]:
        probabilities[list(real["encoder"].classes_).index(crop)] = score
    class Model:
        def predict_proba(self, _):
            return np.array([probabilities])
    monkeypatch.setattr(module, "BUNDLE", {**real, "models": {"random_forest": Model(), "xgboost": Model()}})

def test_market_can_rerank_only_suitable_crops(client, ambiguous_models):
    market = {crop: {"price_per_kg": price, "yield_kg_per_hectare": 1000, "cost_per_hectare": 10000}
              for crop, price in [("rice", 20), ("jute", 50), ("apple", 1000)]}
    result = client.post("/api/recommend", json={**SAMPLE, "market": market, "market_weight": 1}).json
    assert result["market_ranking_applied"]
    assert result["recommendations"][0]["crop"] == "jute"
    assert "apple" not in [crop["crop"] for crop in result["recommendations"]]
    assert result["comparison"]["random_forest"]["crop"] == "rice"

def test_incomplete_market_does_not_bias_ranking(client, ambiguous_models):
    result = client.post("/api/recommend", json={**SAMPLE, "market_weight": 1, "market": {
        "jute": {"price_per_kg": 50, "yield_kg_per_hectare": 1000, "cost_per_hectare": 10000}}}).json
    assert not result["market_ranking_applied"]
    assert result["recommendations"][0]["crop"] == "rice"
    assert any("every suitable candidate" in warning for warning in result["warnings"])

def test_uniform_low_support_does_not_return_a_false_recommendation(client, monkeypatch):
    real = module.bundle()
    class Model:
        def predict_proba(self, _):
            return np.full((1, 22), 1 / 22)
    monkeypatch.setattr(module, "BUNDLE", {**real, "models": {"random_forest": Model(), "xgboost": Model()}})
    response = client.post("/api/recommend", json=SAMPLE)
    assert response.status_code == 422
    assert "minimum model-support" in response.json["error"]
