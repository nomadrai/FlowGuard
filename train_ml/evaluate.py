"""
evaluate.py — HONEST whole-experiment evaluation (leave-one-experiment-out CV).

Per-row train/test splits cheat: readings inside one experiment are heavily
autocorrelated, so the model could just memorise neighbouring rows. Instead,
this script holds out an ENTIRE experiment, trains on the other 15, and
predicts the held-out experiment from scratch — exactly how the pipeline is
used in the field (train once, then stream an unseen experiment).

For every experiment it reports Accuracy / Precision / Recall / F1
(blockage = positive class) plus the macro averages, and writes
train_ml/evaluation_predictions.png: for each of the 16 experiments the true
state (dashed) vs the model prediction (solid), with the water depth for
context.

After the CV it (re)trains the FINAL models on all 16 experiments and saves
them, so train_ml/models/ always holds the best deployable models.

Usage:
    python train_ml/evaluate.py
    python train_ml/evaluate.py --data-dir train_ml/data --out train_ml/models
"""

import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from features import FEATURE_COLUMNS, compute_features
from load_experiments import STATE_BLOCKAGE, load_all
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from train import (
    ALL_EXPERIMENTS,
    NORMAL_EXPERIMENTS,
    build_dataset,
    fit_expected_rate,
    save_models,
    train_models,
)

PLOT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evaluation_predictions.png")
PREDICTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "predictions")


def evaluate_leave_one_out(data_dir, smooth_window=5, random_state=42):
    """Hold out each experiment whole, train on the rest, collect predictions."""
    experiments = load_all(data_dir, numbers=ALL_EXPERIMENTS)
    results = []
    for held_number, held_name, held_df in experiments:
        # Expected-rate model: learned from the normal experiments (1-4),
        # minus the held-out one when it is itself a normal experiment.
        normal_nums = [n for n in NORMAL_EXPERIMENTS if n != held_number]
        expected_model = fit_expected_rate(
            data_dir, numbers=normal_nums, smooth_window=smooth_window
        )

        train_nums = [n for n, _, _ in experiments if n != held_number]
        train_ds = build_dataset(
            data_dir, numbers=train_nums, expected_model=expected_model, smooth_window=smooth_window
        )
        rf, _iso, _X, _y = train_models(train_ds, random_state=random_state)

        held_feats = compute_features(
            held_df, expected_model=expected_model, smooth_window=smooth_window
        )
        X_held = held_feats[FEATURE_COLUMNS].to_numpy()
        finite = np.isfinite(X_held).all(axis=1)
        y_true = (held_df["state"].to_numpy()[finite] == STATE_BLOCKAGE).astype(int)
        y_pred = rf.predict(X_held[finite])

        results.append(
            {
                "number": held_number,
                "name": held_name,
                "timestamp": held_df["timestamp"].to_numpy()[finite],
                "water_depth": held_df["water_depth"].to_numpy()[finite],
                "y_true": y_true,
                "y_pred": y_pred,
                "accuracy": accuracy_score(y_true, y_pred),
                "precision": precision_score(y_true, y_pred, zero_division=0),
                "recall": recall_score(y_true, y_pred, zero_division=0),
                "f1": f1_score(y_true, y_pred, zero_division=0),
                "n": int(len(y_true)),
                "blocked_frac": float(y_true.mean()),
            }
        )
    return results


def _macro(results, key):
    return float(np.mean([r[key] for r in results]))


def print_report(results):
    print("\n=== Whole-experiment evaluation (leave-one-experiment-out) ===")
    print(f"{'exp':>4} {'n':>5} {'blocked%':>8} {'acc':>6} {'prec':>6} {'rec':>6} {'f1':>6}")
    for r in results:
        print(
            f"{r['name']:>13} {r['n']:>5} {100*r['blocked_frac']:>7.1f}% "
            f"{r['accuracy']:>6.3f} {r['precision']:>6.3f} {r['recall']:>6.3f} {r['f1']:>6.3f}"
        )
    print("-" * 53)
    for metric in ("accuracy", "precision", "recall", "f1"):
        print(f"macro {metric:<9s} {_macro(results, metric):.3f}")


def plot_predictions(results, path):
    """4x4 grid: true vs predicted state over time for every experiment."""
    n = len(results)
    cols = 4
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(16, 3.2 * rows), squeeze=False)
    fig.suptitle(
        "FlowGuard ML — whole-experiment predictions (leave-one-out)",
        fontsize=14,
        fontweight="bold",
    )

    for i, r in enumerate(results):
        ax = axes[i // cols][i % cols]
        t = r["timestamp"]
        depth = r["water_depth"]
        ax.plot(t, depth, color="#9EC7DE", linewidth=0.8, label="water depth (cm)")
        ax.step(
            t,
            r["y_true"],
            where="post",
            color="black",
            linestyle="--",
            linewidth=1.0,
            label="true state",
        )
        ax.step(t, r["y_pred"], where="post", color="#D64541", linewidth=1.6, label="predicted")
        ax.set_title(f"{r['name']}  acc={r['accuracy']:.2f}", fontsize=9)
        ax.set_ylim(-0.15, max(1.0, float(np.nanmax(depth)) * 1.05))
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["CLEAR", "BLOCKAGE"])
        ax.tick_params(labelsize=7)
        if i % cols == 0:
            ax.set_ylabel("state", fontsize=8)
        else:
            ax.set_yticklabels([])

    for j in range(n, rows * cols):
        axes[j // cols][j % cols].axis("off")

    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=9, frameon=False)
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Whole-experiment evaluation (leave-one-out CV)")
    parser.add_argument(
        "--data-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    )
    parser.add_argument(
        "--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
    )
    parser.add_argument("--smooth-window", type=int, default=5)
    args = parser.parse_args()

    results = evaluate_leave_one_out(args.data_dir, args.smooth_window)
    print_report(results)

    os.makedirs(PREDICTIONS_PATH, exist_ok=True)
    plot_predictions(results, PLOT_PATH)
    print(f"\nPrediction plot saved: {PLOT_PATH}")

    # Final models on ALL experiments — the deployable artifacts.
    expected_model = fit_expected_rate(args.data_dir, NORMAL_EXPERIMENTS, args.smooth_window)
    dataset = build_dataset(
        args.data_dir,
        ALL_EXPERIMENTS,
        expected_model=expected_model,
        smooth_window=args.smooth_window,
    )
    rf, iso, _X, _y = train_models(dataset)
    save_models(rf, iso, expected_model, args.out)
    print(f"Final models retrained on all 16 experiments and saved to {args.out}/")


if __name__ == "__main__":
    main()
