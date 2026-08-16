"""
predict_experiment.py — run an UNSEEN experiment through the saved models.

No retraining: loads train_ml/models/*.joblib (produced by train.py or
evaluate.py), computes the same features, and predicts CLEAR/BLOCKAGE for
every reading. A prediction plot is saved to train_ml/predictions/ and, if
the CSV carries a state column, Accuracy/Precision/Recall/F1 are reported.

Usage:
    python train_ml/predict_experiment.py --experiment 17
    python train_ml/predict_experiment.py --file /path/to/any_experiment.csv
"""

import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from features import FEATURE_COLUMNS, compute_features
from load_experiments import DATA_DIR, STATE_BLOCKAGE, load_experiment
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from train import load_models

PREDICTIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "predictions")


def predict(experiment_df, expected_model, rf, iso):
    """Compute features and return (y_true, y_pred_rf, y_pred_iso, features)."""
    feats = compute_features(experiment_df, expected_model=expected_model)
    X = feats[FEATURE_COLUMNS].to_numpy()
    finite = np.isfinite(X).all(axis=1)
    y_true = (experiment_df["state"].to_numpy() == STATE_BLOCKAGE).astype(int)

    y_pred_rf = np.full(len(X), -1, dtype=int)
    y_pred_iso = np.full(len(X), -1, dtype=int)
    y_pred_rf[finite] = rf.predict(X[finite])
    y_pred_iso[finite] = (iso.predict(X[finite]) == -1).astype(int)
    return y_true, y_pred_rf, y_pred_iso, feats


def print_metrics(name, y_true, y_pred):
    mask = y_pred != -1
    if not mask.any():
        print(f"  {name}: no usable rows")
        return
    yt, yp = y_true[mask], y_pred[mask]
    if yt.sum() == 0 or (1 - yt).sum() == 0:
        # Single-class experiment: report accuracy only.
        print(
            f"  {name}: accuracy {accuracy_score(yt, yp):.3f} "
            f"(single-class experiment, {int(yt.sum())} blocked rows)"
        )
        return
    print(
        f"  {name}: acc {accuracy_score(yt, yp):.3f} | prec "
        f"{precision_score(yt, yp, zero_division=0):.3f} | rec "
        f"{recall_score(yt, yp, zero_division=0):.3f} | f1 "
        f"{f1_score(yt, yp, zero_division=0):.3f}"
    )


def plot_experiment(experiment_df, y_true, y_pred_rf, path, title):
    fig, ax = plt.subplots(figsize=(11, 3.6))
    t = experiment_df["timestamp"].to_numpy()
    depth = experiment_df["water_depth"].to_numpy()
    ax.plot(t, depth, color="#9EC7DE", linewidth=0.8, label="water depth (cm)")
    ax.step(
        t, y_true, where="post", color="black", linestyle="--", linewidth=1.0, label="true state"
    )
    ax.step(t, y_pred_rf, where="post", color="#D64541", linewidth=1.6, label="predicted")
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_ylim(-0.15, max(1.0, float(np.nanmax(depth)) * 1.05))
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["CLEAR", "BLOCKAGE"])
    ax.set_xlabel("time (s)")
    ax.legend(loc="upper left", ncol=3, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Predict states for an unseen experiment")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--experiment", type=int, help="experiment number (uses data/experiment_XX.csv)"
    )
    group.add_argument("--file", help="direct path to an experiment CSV")
    parser.add_argument("--data-dir", default=DATA_DIR)
    parser.add_argument(
        "--models-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
    )
    args = parser.parse_args()

    if args.file:
        path, number = args.file, None
    else:
        path = os.path.join(args.data_dir, f"experiment_{args.experiment:02d}.csv")
        number = args.experiment
    if not os.path.exists(path):
        raise SystemExit(f"{path} not found")

    experiment_df = load_experiment(path, number=number)
    expected_model, rf, iso, meta = load_models(args.models_dir)
    y_true, y_pred_rf, y_pred_iso, feats = predict(experiment_df, expected_model, rf, iso)

    print(f"\nExperiment: {os.path.basename(path)}  ({len(experiment_df)} readings)")
    print(f"Using models from: {args.models_dir}")
    print(f"Features: {meta['feature_columns']}")
    print("\nMetrics (vs recorded state, when present):")
    print_metrics("RandomForest  ", y_true, y_pred_rf)
    print_metrics("IsolationForest", y_true, y_pred_iso)

    os.makedirs(PREDICTIONS_DIR, exist_ok=True)
    plot_path = os.path.join(
        PREDICTIONS_DIR, f"{os.path.splitext(os.path.basename(path))[0]}_prediction.png"
    )
    plot_experiment(experiment_df, y_true, y_pred_rf, plot_path, os.path.basename(path))
    print(f"\nPrediction plot: {plot_path}")

    flips = np.diff(y_pred_rf)
    n_flips = int(np.abs(flips).sum())
    print(
        f"Prediction changed state {n_flips} time(s) "
        f"({int((y_pred_rf == 1).sum())} readings flagged BLOCKAGE)"
    )


if __name__ == "__main__":
    main()
