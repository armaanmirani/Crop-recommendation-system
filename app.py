"""Flask application: ML suitability, with an explicitly separate planning layer."""
from pathlib import Path
import math
import os
import joblib
import pandas as pd
import market as market_service
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType
from train import FEATURES

ROOT = Path(__file__).resolve().parent
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2_000_000
BUNDLE = None
LIMITS = {"N": (0, 300), "P": (0, 300), "K": (0, 300), "temperature": (-10, 60),
          "humidity": (0, 100), "ph": (0, 14), "rainfall": (0, 5000)}
# Qualitative demo categories, not learned water-demand measurements.
WATER = {
    "rice": "high", "jute": "high", "banana": "high", "coconut": "high",
    "coffee": "high", "papaya": "high", "maize": "medium", "cotton": "medium",
    "apple": "medium", "orange": "medium", "grapes": "medium", "mango": "medium",
    "muskmelon": "medium", "watermelon": "medium", "pomegranate": "medium",
    "chickpea": "low", "lentil": "low", "mungbean": "low", "mothbeans": "low",
    "blackgram": "low", "pigeonpeas": "low", "kidneybeans": "medium",
}
LEGUMES = {"chickpea", "lentil", "mungbean", "mothbeans", "blackgram", "pigeonpeas", "kidneybeans"}


def bundle():
    global BUNDLE
    if BUNDLE is None:
        path = ROOT / "models" / "crop_models.joblib"
        if not path.exists():
            raise RuntimeError("Models are missing. Run python train.py before starting the app.")
        BUNDLE = joblib.load(path)  # Only load this project's locally generated artifact.
    return BUNDLE


def number(value, name, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number.")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number.") from None
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return result


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/metadata")
def metadata():
    return jsonify(bundle()["metadata"])


@app.get("/api/health")
def health():
    return jsonify(status="ready", models=list(bundle()["models"]))


@app.get("/api/market-status")
def market_status():
    return jsonify(api_key_configured=bool(os.environ.get("DATA_GOV_API_KEY", "").strip()),
                   commodities=market_service.COMMODITIES, source="Agmarknet via data.gov.in",
                   source_url=market_service.SOURCE_URL, portal_url=market_service.PORTAL_URL,
                   freshness_limit_days=market_service.STALE_DAYS)


@app.get("/api/market-prices")
def market_prices():
    try:
        return jsonify(market_service.fetch_prices(request.args))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except market_service.MarketError as exc:
        app.logger.warning("Market lookup failed: code=%s status=%s", exc.code, exc.status)
        return jsonify(error=str(exc), error_code=exc.code), exc.status


@app.post("/api/market-import")
def market_import():
    try:
        uploaded = request.files.get("file")
        if uploaded is None:
            raise ValueError("Choose an official CSV export to import.")
        return jsonify(market_service.import_csv(uploaded.read(), request.form))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="Upload/request exceeds the 2 MB limit. Export a narrower location or date range."), 413


@app.post("/api/recommend")
def recommend():
    try:
        body = request.get_json()
        if not isinstance(body, dict):
            raise ValueError("Send a JSON object containing field measurements.")
        values = {key: number(body.get(key), key, *LIMITS[key]) for key in FEATURES}
        data = bundle()
        model_name = body.get("model", data["metadata"]["selected_model"])
        if not isinstance(model_name, str) or model_name not in data["models"]:
            raise ValueError("Choose random_forest or xgboost.")
        water = body.get("water_availability", "medium")
        if water not in ("low", "medium", "high"):
            raise ValueError("Water availability must be low, medium, or high.")
        area = number(body.get("area_hectares", 1), "Area (hectares)", .01, 100000)
        preference = number(body.get("market_weight", 0), "Market priority", 0, 1)
        markets = body.get("market", {})
        if not isinstance(markets, dict) or any(k not in data["metadata"]["crops"] for k in markets):
            raise ValueError("Market entries must use supported crop names.")
        economics = {}
        for crop, inputs in markets.items():
            if not isinstance(inputs, dict):
                raise ValueError(f"Market details for {crop} must be an object.")
            quote = market_service.resolve_quote(inputs["quote_id"], crop) if "quote_id" in inputs else None
            price = number(quote["price_per_kg"] if quote else inputs.get("price_per_kg"), f"{crop} price/kg", 0, 1000000)
            yield_kg = number(inputs.get("yield_kg_per_hectare"), f"{crop} yield kg/ha", 0, 1000000)
            cost = number(inputs.get("cost_per_hectare"), f"{crop} cost/ha", 0, 1000000000)
            economics[crop] = {"price_per_kg": price, "yield_kg_per_hectare": yield_kg,
                               "cost_per_hectare": cost, "estimated_profit": (price * yield_kg - cost) * area,
                               "price_source": quote if quote else {"source": "Manual estimate"}}
    except (ValueError, BadRequest, UnsupportedMediaType) as exc:
        return jsonify(error=str(exc)), 400

    frame = pd.DataFrame([values], columns=FEATURES)
    all_predictions = {name: model.predict_proba(frame)[0] for name, model in data["models"].items()}
    probabilities = all_predictions[model_name]
    crops = data["encoder"].classes_.tolist()
    best = float(max(probabilities))
    # Financial preference cannot promote crops with very low model support.
    candidates = [i for i, probability in enumerate(probabilities) if probability >= max(.05, best * .25)]
    if not candidates:
        return jsonify(error="No crop meets the minimum model-support threshold. Verify your field measurements and consult local agricultural guidance."), 422
    complete_market = len(candidates) > 1 and all(crops[i] in economics for i in candidates)
    warnings = []
    effective_weight = preference if complete_market else 0
    if preference and not complete_market:
        warnings.append("Market ranking requires price, yield, and cost for every suitable candidate and at least two candidates. Suitability ranking is retained.")
    profits = [economics[crops[i]]["estimated_profit"] for i in candidates] if complete_market else []
    spread = max(profits) - min(profits) if profits else 0
    rows = []
    for i in candidates:
        crop = crops[i]
        market_score = (economics[crop]["estimated_profit"] - min(profits)) / spread if spread else 0
        # Equal profits do not change the agronomic order.
        weight = effective_weight if spread else 0
        score = (1 - weight) * float(probabilities[i]) / best + weight * market_score
        rows.append({"crop": crop, "suitability": float(probabilities[i]), "planning_score": score,
                     "market": economics.get(crop), "water_need": WATER[crop],
                     "water_caution": WATER[crop] == "high" and water != "high",
                     "rotation_note": "Legume: may support nitrogen-fixing rotations; check local guidance." if crop in LEGUMES else "Plan rotation with locally suitable crops to protect soil health."})
    rows.sort(key=lambda row: row["planning_score"], reverse=True)
    for key in FEATURES:
        limits = data["metadata"]["feature_ranges"][key]
        if values[key] < limits["min"] or values[key] > limits["max"]:
            warnings.append(f"{key} is outside the training data range ({limits['min']:.1f}–{limits['max']:.1f}); model scores may be unreliable.")
    if best < .5:
        warnings.append("No crop has strong model support. Confirm measurements and consult a local agronomist.")
    if rows[0]["water_caution"]:
        warnings.append("The leading crop has a high demo water-demand category. Confirm a sustainable irrigation supply before planting.")
    comparison = {name: {"crop": crops[int(probs.argmax())], "suitability": float(probs.max())}
                  for name, probs in all_predictions.items()}
    if len({item["crop"] for item in comparison.values()}) > 1:
        warnings.append("The two models disagree on the leading crop. Review the alternatives and local growing conditions.")
    return jsonify(recommendations=rows, comparison=comparison, model=model_name,
                   market_ranking_applied=bool(effective_weight and spread), warnings=warnings,
                   inputs=values, area_hectares=area)


if __name__ == "__main__":
    bundle()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
