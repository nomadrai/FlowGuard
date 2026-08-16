"""
features.py — per-reading feature engineering for the ML models.

Every feature is computed at a single reading's timestep, so the trained
models can be applied to live streamed readings with the same layout:

    water_depth     current water depth (cm)        [the absolute level is
                                                     never used as a threshold]
    rate            rise/fall rate (cm/s)           first difference over dt
    smoothed_rate   rolling mean of rate            kills HC-SR04 noise
    rate_change     acceleration: change of rate    vs the previous step
    expected_rate   normal rise rate expected at the current depth (cm/s),
                    from ExpectedRateModel trained on experiments 1-4
    rate_deviation  rate - expected_rate            <-- the actual ML signal

A negative rate (water falling) or a rate near/below the depth-expected value
is CLEAR; a rate clearly above the depth-expected value is BLOCKAGE.
"""

import numpy as np
import pandas as pd

FEATURE_COLUMNS = [
    "water_depth",
    "rate",
    "smoothed_rate",
    "rate_change",
    "expected_rate",
    "rate_deviation",
]


def compute_features(df, expected_model=None, smooth_window=5):
    """
    Compute the per-reading feature frame from an experiment DataFrame
    (columns: timestamp, water_depth). Row order is preserved.

    expected_model: ExpectedRateModel instance; when None the expected_rate /
        rate_deviation columns are NaN (used to fit the model from the rate
        column before the final feature pass).
    """
    out = pd.DataFrame(index=df.index)
    out["water_depth"] = df["water_depth"].astype(float)

    dt = df["timestamp"].diff().to_numpy()
    dt = np.where(np.isfinite(dt) & (dt > 0), dt, np.nan)
    rate = df["water_depth"].diff().to_numpy() / dt
    rate = np.nan_to_num(rate, nan=0.0, posinf=0.0, neginf=0.0)
    out["rate"] = rate
    out["smoothed_rate"] = pd.Series(rate).rolling(smooth_window, min_periods=1).mean().to_numpy()
    out["rate_change"] = np.diff(rate, prepend=0.0)

    if expected_model is not None:
        out["expected_rate"] = expected_model.predict(out["water_depth"].to_numpy())
        out["rate_deviation"] = out["rate"] - out["expected_rate"]
    else:
        out["expected_rate"] = np.nan
        out["rate_deviation"] = np.nan
    return out


if __name__ == "__main__":
    import numpy as np

    # Self-check on a tiny artificial series.
    df = pd.DataFrame(
        {"timestamp": np.arange(6, dtype=float), "water_depth": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]}
    )
    feats = compute_features(df, expected_model=None)
    assert abs(feats["rate"].iloc[1] - 1.0) < 1e-9
    assert feats["rate"].iloc[0] == 0.0
    assert list(feats.columns) == FEATURE_COLUMNS
    assert feats["expected_rate"].isna().all()
    print("features self-check passed.")
