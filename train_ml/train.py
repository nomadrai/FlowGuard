"""
train.py — build the experiment dataset and train the ML models.

Pipeline:
    1. load experiments 1-16                       (load_experiments.py)
    2. compute per-reading features                (features.py)
    3. learn expected_rise_rate = f(water_depth)   (expected_rate.py)
       from experiments 1-4 — the normal-rainfall, no-blockage experiments
    4. train the main supervised model             RandomForestClassifier
       (BLOCKAGE vs CLEAR, class-balanced) and the existing baseline
       IsolationForest
    5. save everything with joblib into train_ml/models/

The absolute water depth is never a decision threshold — the models decide
on RATE signals relative to the depth-expected normal rate.

Usage:
    python train_ml/train.py
    python train_ml/train.py --data-dir train_ml/data --out train_ml/models
"""

import argparse
import json
import os

import joblib
import numpy as np
import pandas as pd
from expected_rate import ExpectedRateModel
from features import FEATURE_COLUMNS, compute_features
from load_experiments import DATA_DIR, STATE_BLOCKAGE, load_all
from sklearn.ensemble import IsolationForest, RandomForestClassifier

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
NORMAL_EXPERIMENTS = list(range(1, 5))
ALL_EXPERIMENTS = list(range(1, 17))
RANDOM_STATE = 42


def fit_expected_rate(data_dir=DATA_DIR, numbers=NORMAL_EXPERIMENTS, smooth_window=5):
    """
    Learn expected_rise_rate = f(water_depth) from the NORMAL-rainfall
    experiments (1-4 by default) — clean, no-blockage behaviour only.

    All samples (rising AND equilibrium-flat) are used: at equilibrium the
    normal rate is ~0, so the learned curve correctly drops towards zero at
    the depths the water settles at — a blocked pipe rises faster than that.
    """
    frames = []
    for _number, _name, df in load_all(data_dir, numbers):
        feats = compute_features(df, expected_model=None, smooth_window=smooth_window)
        frames.append(feats[["water_depth", "rate"]])
    concat = pd.concat(frames, ignore_index=True)
    if len(concat) < 4:
        raise ValueError(
            "not enough (depth, rate) samples in the normal experiments — "
            "record longer experiments 1-4"
        )
    return ExpectedRateModel().fit(concat["water_depth"], concat["rate"])


def build_dataset(data_dir=DATA_DIR, numbers=ALL_EXPERIMENTS, expected_model=None, smooth_window=5):
    """
    Load the requested experiments and compute the feature frame for every
    reading, with the state label attached.
    """
    experiments = load_all(data_dir, numbers)
    frames = []
    for number, name, df in experiments:
        feats = compute_features(df, expected_model=expected_model, smooth_window=smooth_window)
        feats["state"] = df["state"].to_numpy()
        feats["experiment_number"] = number
        feats["experiment_name"] = name
        frames.append(feats)
    return pd.concat(frames, ignore_index=True)


def train_models(dataset, random_state=RANDOM_STATE):
    """
    Train RandomForestClassifier (main model) and IsolationForest (baseline)
    on the feature frame. BLOCKAGE -> 1, CLEAR -> 0. Rows with NaN features
    are dropped; the indices are returned so predictions can be mapped back.
    """
    X = dataset[FEATURE_COLUMNS].to_numpy()
    y = (dataset["state"].to_numpy() == STATE_BLOCKAGE).astype(int)
    finite = np.isfinite(X).all(axis=1)
    X, y = X[finite], y[finite]

    rf = RandomForestClassifier(
        n_estimators=300,
        min_samples_leaf=1,
        class_weight="balanced",
        random_state=random_state,
        n_jobs=-1,
    )
    rf.fit(X, y)

    contamination = max(0.001, min(float(y.mean()), 0.5))
    iso = IsolationForest(contamination=contamination, random_state=random_state)
    iso.fit(X)
    return rf, iso, X, y


def save_models(rf, iso, expected_model, out_dir=MODELS_DIR, extra=None):
    """Persist the trained models + the feature-column layout with joblib."""
    os.makedirs(out_dir, exist_ok=True)
    joblib.dump(expected_model, os.path.join(out_dir, "expected_rate_model.joblib"))
    joblib.dump(rf, os.path.join(out_dir, "random_forest.joblib"))
    joblib.dump(iso, os.path.join(out_dir, "isolation_forest.joblib"))
    meta = {"feature_columns": FEATURE_COLUMNS, "random_state": RANDOM_STATE}
    if extra:
        meta.update(extra)
    with open(os.path.join(out_dir, "model_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)


def load_models(models_dir=MODELS_DIR):
    """Load the trained models and metadata back for prediction/evaluation."""
    expected_model = joblib.load(os.path.join(models_dir, "expected_rate_model.joblib"))
    rf = joblib.load(os.path.join(models_dir, "random_forest.joblib"))
    iso = joblib.load(os.path.join(models_dir, "isolation_forest.joblib"))
    with open(os.path.join(models_dir, "model_meta.json")) as f:
        meta = json.load(f)
    return expected_model, rf, iso, meta


def main():
    parser = argparse.ArgumentParser(description="Train FlowGuard ML models on experiments 1-16")
    parser.add_argument(
        "--data-dir", default=DATA_DIR, help="directory with experiment_XX.csv files"
    )
    parser.add_argument("--out", default=MODELS_DIR, help="directory to save the trained models")
    parser.add_argument(
        "--smooth-window", type=int, default=5, help="rate smoothing window (readings)"
    )
    args = parser.parse_args()

    print(f"Loading experiments 1-16 from {args.data_dir} ...")
    expected_model = fit_expected_rate(args.data_dir, NORMAL_EXPERIMENTS, args.smooth_window)
    dataset = build_dataset(
        args.data_dir,
        ALL_EXPERIMENTS,
        expected_model=expected_model,
        smooth_window=args.smooth_window,
    )

    rf, iso, X, y = train_models(dataset)
    save_models(rf, iso, expected_model, args.out, extra={"n_rows": int(len(X))})

    n_clear = int((y == 0).sum())
    n_blocked = int((y == 1).sum())
    print(f"\nTraining samples : {len(X)} rows  ({n_clear} CLEAR / {n_blocked} BLOCKAGE)")
    print(f"Feature columns  : {FEATURE_COLUMNS}")
    print("Expected-rate curve (depth -> normal rate cm/s):")
    for c, r in zip(expected_model.bin_centers_, expected_model.bin_rates_):
        print(f"    depth {c:5.2f} cm -> {r:.4f} cm/s")
    print("\nFeature importances (RandomForest):")
    for name, imp in sorted(zip(FEATURE_COLUMNS, rf.feature_importances_), key=lambda t: -t[1]):
        print(f"    {name:<16s} {imp:.3f}")

    print(f"\nIn-sample accuracy: {rf.score(X, y):.3f}")
    print(
        f"Saved: {args.out}/random_forest.joblib, isolation_forest.joblib, "
        f"expected_rate_model.joblib, model_meta.json"
    )


if __name__ == "__main__":
    main()
