"""
ml_model.py — bridge between the train_ml pipeline and the live FlowGuard app.

Loads the artifacts saved by `train_ml/evaluate.py` (random_forest.joblib,
isolation_forest.joblib, expected_rate_model.joblib, model_meta.json) and
applies them to live readings with EXACTLY the same features the model was
trained on:

    water_depth, rate, smoothed_rate, rate_change, expected_rate,
    rate_deviation

The feature code and the expected-rate model class are imported from
train_ml/ itself (added to sys.path for the pickled ExpectedRateModel), so
the live path can never drift from the training pipeline.

The prediction for the LATEST reading is confirmed only when a MAJORITY of
the last `confirm_window` readings are BLOCKAGE — per-reading predictions
chatter (experiment 17 flips ~20 times over 88 readings), the window
steadies it while keeping detection latency low.

If the artifacts cannot be found/loaded the model stays None and callers
fall back to the legacy on-the-fly IsolationForest — the dashboard never
crashes because the model folder is missing.

Usage:
    from ml_model import get_trained_model

    model = get_trained_model()
    result = model.predict(history)   # history: list of (t_sec, h), oldest -> newest
"""

import json
import os
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

# pyrefly: ignore [missing-import]
from config import ML_CONFIRM_WINDOW, ML_MODELS_DIR

TRAIN_ML_DIR = Path(ML_MODELS_DIR).resolve().parent

# Fallback layout when model_meta.json is missing — model_meta.json is
# authoritative; these only mirror train_ml/features.py.
DEFAULT_FEATURE_COLUMNS = [
    "water_depth",
    "rate",
    "smoothed_rate",
    "rate_change",
    "expected_rate",
    "rate_deviation",
]


def _ensure_train_ml_importable():
    """train_ml/ must be importable: expected_rate_model.joblib pickles the
    custom class expected_rate.ExpectedRateModel by module reference, and the
    feature pipeline is imported from there too."""
    if str(TRAIN_ML_DIR) not in sys.path:
        sys.path.insert(0, str(TRAIN_ML_DIR))


class TrainedMLModel:
    """The trained RandomForest + depth-dependent expected-rate model.

    Stateless wrt readings: pass the full (t_sec, h) history (oldest ->
    newest) each time; every feature is backward-looking, so a single
    vectorised pass produces the per-reading predictions the model would
    have made live.
    """

    def __init__(self, models_dir=None, confirm_window=None):
        self.models_dir = str(models_dir or ML_MODELS_DIR)
        self.confirm_window = int(confirm_window or ML_CONFIRM_WINDOW)
        self._load()

    def _load(self):
        _ensure_train_ml_importable()
        # The feature pipeline lives in train_ml/features.py — importing it
        # here guarantees the live features are identical to training.
        try:
            from features import compute_features
        except ImportError as exc:
            raise ImportError(
                f"train_ml pipeline not importable from {TRAIN_ML_DIR}: {exc}"
            ) from exc
        self.compute_features = compute_features

        self.expected_model = joblib.load(
            os.path.join(self.models_dir, "expected_rate_model.joblib")
        )
        self.rf = joblib.load(os.path.join(self.models_dir, "random_forest.joblib"))
        self.iso = joblib.load(os.path.join(self.models_dir, "isolation_forest.joblib"))
        with open(os.path.join(self.models_dir, "model_meta.json")) as f:
            self.meta = json.load(f)
        self.feature_columns = self.meta.get("feature_columns", DEFAULT_FEATURE_COLUMNS)
        if 1 not in self.rf.classes_:
            raise ValueError("trained RandomForest has no BLOCKAGE class (1)")

    # ------------------------------------------------------------------
    def predict_series(self, history):
        """
        Per-reading CLEAR/BLOCKAGE predictions over the whole history.

        Args:
            history: list of (t_sec, h) pairs, oldest -> newest.

        Returns:
            (y_pred, p_blocked, feats) where y_pred is an int array
            (1 = BLOCKAGE, 0 = CLEAR), p_blocked the RF probability of
            BLOCKAGE per reading, and feats the computed feature frame.
        """
        if not history or len(history) < 2:
            raise ValueError("need at least 2 readings to compute rate features")
        df = pd.DataFrame(history, columns=["timestamp", "water_depth"])
        df["water_depth"] = df["water_depth"].astype(float)
        feats = self.compute_features(df, expected_model=self.expected_model)
        x = feats[self.feature_columns].to_numpy()
        finite = np.isfinite(x).all(axis=1)

        y_pred = np.zeros(len(x), dtype=int)
        p_blocked = np.zeros(len(x), dtype=float)
        if finite.any():
            y_pred[finite] = self.rf.predict(x[finite])
            p_blocked[finite] = self.rf.predict_proba(x[finite])[:, list(self.rf.classes_).index(1)]
        return y_pred, p_blocked, feats

    def predict(self, history):
        """
        Prediction for the LATEST reading, confirmed by a majority of the
        last `confirm_window` readings.

        Args:
            history: list of (t_sec, h) pairs, oldest -> newest.

        Returns:
            dict with prediction, blocked (bool), proba_blocked,
            iso_anomaly, n_readings, n_blocked_recent, and the latest
            feature values — or None when too few readings.
        """
        if not history or len(history) < 2:
            return None
        try:
            y_pred, p_blocked, feats = self.predict_series(history)
        except ValueError:
            return None

        window = max(1, min(self.confirm_window, len(y_pred)))
        recent = y_pred[-window:]
        n_blocked_recent = int(recent.sum())
        blocked = n_blocked_recent > window / 2.0

        iso_x = feats[self.feature_columns].to_numpy()
        iso_anomaly = False
        if np.isfinite(iso_x[-1]).all():
            iso_anomaly = bool(self.iso.predict(iso_x[-1:])[0] == -1)

        return {
            "prediction": "BLOCKAGE" if blocked else "CLEAR",
            "blocked": blocked,
            "proba_blocked": float(p_blocked[-1]),
            "iso_anomaly": iso_anomaly,
            "n_readings": int(len(y_pred)),
            "n_blocked_recent": n_blocked_recent,
            "confirm_window": window,
            "depth": float(feats["water_depth"].iloc[-1]),
            "rate": float(feats["rate"].iloc[-1]),
            "smoothed_rate": float(feats["smoothed_rate"].iloc[-1]),
            "expected_rate": float(feats["expected_rate"].iloc[-1]),
            "rate_deviation": float(feats["rate_deviation"].iloc[-1]),
        }


_MODEL = None
_MODEL_TRIED = False


def get_trained_model():
    """Module-level singleton: loads the trained models once, returns None
    (without raising) when the artifacts are missing or broken — callers
    fall back to the legacy detection path."""
    global _MODEL, _MODEL_TRIED
    if _MODEL_TRIED:
        return _MODEL
    _MODEL_TRIED = True
    try:
        _MODEL = TrainedMLModel()
    except (FileNotFoundError, ImportError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"[ml_model] trained model unavailable ({exc}) — falling back to on-the-fly ML")
        _MODEL = None
    return _MODEL


if __name__ == "__main__":
    # Self-test: score the unseen experiment 17 the same way
    # train_ml/predict_experiment.py does.
    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

    _ensure_train_ml_importable()
    from load_experiments import STATE_BLOCKAGE, load_experiment

    exp_path = TRAIN_ML_DIR / "data" / "experiment_17.csv"
    if not exp_path.exists():
        raise SystemExit(f"{exp_path} not found — record experiment 17 first")

    exp = load_experiment(str(exp_path), number=17)
    history = list(zip(exp["timestamp"].to_numpy(), exp["water_depth"].to_numpy()))
    y_true = (exp["state"].to_numpy() == STATE_BLOCKAGE).astype(int)

    model = get_trained_model()
    if model is None:
        raise SystemExit(
            "trained model could not be loaded — run train_ml/train.py + evaluate.py first"
        )

    y_pred, p_blocked, feats = model.predict_series(history)
    print(f"Experiment 17: {len(history)} readings, RF per-reading metrics")
    print(
        f"  acc {accuracy_score(y_true, y_pred):.3f} | prec "
        f"{precision_score(y_true, y_pred, zero_division=0):.3f} | rec "
        f"{recall_score(y_true, y_pred, zero_division=0):.3f} | f1 "
        f"{f1_score(y_true, y_pred, zero_division=0):.3f}"
    )
    print(f"  per-reading flips: {int(np.abs(np.diff(y_pred)).sum())}")

    result = model.predict(history)
    print(
        f"  latest-reading verdict: {result['prediction']} "
        f"(blocked={result['blocked']}, proba={result['proba_blocked']:.3f}, "
        f"iso={result['iso_anomaly']}, recent {result['n_blocked_recent']}/{result['confirm_window']})"
    )
    print("ml_model self-check passed.")
