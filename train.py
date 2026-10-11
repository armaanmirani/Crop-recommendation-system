"""Reproducible crop classification with validation selection and held-out testing."""
from pathlib import Path
import hashlib
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parent
FEATURES = ["N", "P", "K", "temperature", "humidity", "ph", "rainfall"]
DATA = ROOT / "data" / "Crop_recommendation.csv"


def train():
    df = pd.read_csv(DATA)
    if list(df.columns) != FEATURES + ["label"] or df.isna().any().any():
        raise ValueError("Dataset must contain the seven numeric features and label, without missing values.")
    if df.duplicated().any() or not np.isfinite(df[FEATURES].to_numpy()).all():
        raise ValueError("Dataset contains duplicate rows or non-finite features.")
    encoder = LabelEncoder().fit(df.label)
    X, y = df[FEATURES], encoder.transform(df.label)
    X_dev, X_test, y_dev, y_test = train_test_split(X, y, test_size=.2, stratify=y, random_state=42)
    X_train, X_val, y_train, y_val = train_test_split(X_dev, y_dev, test_size=.25, stratify=y_dev, random_state=42)
    models = {
        "random_forest": RandomForestClassifier(n_estimators=300, max_features="sqrt", random_state=42, n_jobs=2),
        "xgboost": XGBClassifier(n_estimators=250, max_depth=4, learning_rate=.08, subsample=.9,
                                 colsample_bytree=.9, objective="multi:softprob", eval_metric="mlogloss",
                                 tree_method="hist", random_state=42, n_jobs=2),
    }
    validation = {}
    for name, model in models.items():
        model.fit(X_train, y_train)
        validation[name] = float(f1_score(y_val, model.predict(X_val), average="macro"))
    selected = max(validation, key=validation.get)
    metrics = {}
    for name, model in models.items():
        model.fit(X_dev, y_dev)
        prediction = model.predict(X_test)
        metrics[name] = {
            "accuracy": float(accuracy_score(y_test, prediction)),
            "macro_f1": float(f1_score(y_test, prediction, average="macro")),
            "validation_macro_f1": validation[name],
            "classification_report": classification_report(y_test, prediction, target_names=encoder.classes_, output_dict=True),
            "confusion_matrix": confusion_matrix(y_test, prediction).tolist(),
            "feature_importance": dict(zip(FEATURES, map(float, model.feature_importances_))),
        }
    metadata = {
        "features": FEATURES, "crops": encoder.classes_.tolist(), "samples": len(df),
        "split": {"training": len(X_train), "validation": len(X_val), "test": len(X_test), "final_training": len(X_dev)},
        "seed": 42, "selected_model": selected, "metrics": metrics,
        "feature_ranges": {key: {"min": float(df[key].min()), "max": float(df[key].max())} for key in FEATURES},
        "dataset_sha256": hashlib.sha256(DATA.read_bytes()).hexdigest(),
        "source": "Kaggle Crop Recommendation Dataset (Atharva Ingle), obtained from Harvestify's public mirror",
        "selection": "Highest validation macro-F1; refit on training + validation; test set remains unseen.",
    }
    output = ROOT / "models"
    output.mkdir(exist_ok=True)
    joblib.dump({"models": models, "encoder": encoder, "metadata": metadata}, output / "crop_models.joblib")
    (output / "metrics.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({"selected_model": selected, "test": {k: {m: v[m] for m in ("accuracy", "macro_f1")} for k, v in metrics.items()}}, indent=2))
    return metadata


if __name__ == "__main__":
    train()
