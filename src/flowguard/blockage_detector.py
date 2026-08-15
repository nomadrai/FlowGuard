"""
blockage_detector.py — FlowGuard's core physics + ML detection engine.

Three layers, stacked:
  1. PHYSICS: orifice equation (from Bernoulli) — converts live water height
     readings into a calculated open channel area.
  2. ML CONFIRMATION: a single noisy reading doesn't mean much (a splash,
     a sensor glitch). We keep a rolling window of blockage-% estimates,
     extract simple features (mean, trend/slope, volatility), and run an
     Isolation Forest trained on KNOWN-CLEAN behaviour to decide whether a
     sustained pattern is a real anomaly — not just point-in-time noise.
  3. TREND FORECAST: linear regression on blockage-% over time, projected
     forward to estimate "days until this segment crosses a critical
     blockage threshold" — the same "time-to-critical" idea used in
     predictive-maintenance systems, applied here to infrastructure decay.

Usage as a library — see test block at bottom for a runnable example.
"""

import numpy as np
from sklearn.ensemble import IsolationForest

from config import PIPE_DIAMETER_CM, PIPE_AREA_CM2, INLET_BOX_BASE_AREA_CM2

G_CM_S2 = 981.0  # gravity, cm/s^2 (centimeter units throughout this module)

# NOTE: PIPE_DIAMETER_CM, PIPE_AREA_CM2, INLET_BOX_BASE_AREA_CM2 now come from
# config.py — the single shared source of truth across all FlowGuard files.
# (Previously duplicated here, which risked drifting out of sync with the
# dashboard's copy — exactly the kind of mismatch that caused a false
# blockage reading during development.)


# ------------------------------------------------------------------
# LAYER 1 — PHYSICS (orifice equation, from Bernoulli's principle)
# ------------------------------------------------------------------

def calibrate_cd(pour_volume_ml, pour_time_sec, steady_h_cm, a_clean_cm2):
    """
    Run this ONCE per physical channel, using a clean (unblocked) test pour.
    Returns the calibrated discharge coefficient Cd for this specific channel.

    pour_volume_ml: total water poured (mL == cm^3)
    pour_time_sec:  how long the pour took (seconds)
    steady_h_cm:    water height reading once level stabilized (cm)
    a_clean_cm2:    known clean channel opening area (measured with ruler)
    """
    q = pour_volume_ml / pour_time_sec  # cm^3/s
    if steady_h_cm <= 0:
        raise ValueError("steady_h_cm must be > 0 — can't calibrate from a dry reading")
    cd = q / (a_clean_cm2 * np.sqrt(2 * G_CM_S2 * steady_h_cm))
    return cd


def calculate_area(q_cm3_s, cd, h_cm):
    """
    LIVE calculation: given current inflow (Q) and measured water height (h),
    back-calculate the channel's CURRENT effective open area.
    A smaller-than-expected result indicates a blockage.
    """
    if h_cm <= 0:
        return None  # channel dry, no flow to analyze
    denom = cd * np.sqrt(2 * G_CM_S2 * h_cm)
    if denom == 0:
        return None
    return q_cm3_s / denom


def blockage_percent(a_calculated_cm2, a_clean_cm2):
    """
    Positive % = that much of the channel's capacity is lost to blockage.
    Negative or ~0 = channel is clear (or even reading slightly over,
    which just means measurement noise around 0%).
    """
    if a_calculated_cm2 is None:
        return None
    pct = (a_clean_cm2 - a_calculated_cm2) / a_clean_cm2 * 100.0
    return pct


# ------------------------------------------------------------------
# LAYER 2 — ML CONFIRMATION (Isolation Forest on rolling windows)
# ------------------------------------------------------------------

def extract_window_features(blockage_pct_series):
    """
    From a rolling window of blockage-% readings, extract features that
    describe the PATTERN, not just the latest point:
      - mean level
      - trend (slope) — is it climbing, or just noisy around a flat line?
      - volatility (std) — is this a wild single spike or a sustained shift?
    """
    arr = np.array(blockage_pct_series, dtype=float)
    if len(arr) < 2:
        return None
    x = np.arange(len(arr))
    slope = np.polyfit(x, arr, 1)[0]  # rate of change per reading
    mean_val = arr.mean()
    std_val = arr.std()
    return np.array([mean_val, slope, std_val])


class BlockageAnomalyDetector:
    """
    Fit this ONCE on windows drawn from known-clean behaviour (e.g., your
    calibration run, or early "no blockage" readings). It then flags future
    windows that look statistically different — a real, sustained pattern
    shift — rather than a single noisy point.
    """

    def __init__(self, contamination=0.1):
        self.model = IsolationForest(contamination=contamination, random_state=42)
        self.fitted = False

    def fit(self, clean_windows_features):
        """clean_windows_features: list of feature arrays from extract_window_features on clean data."""
        X = np.array(clean_windows_features)
        self.model.fit(X)
        self.fitted = True

    def is_confirmed_anomaly(self, window_features):
        """Returns True if this window's pattern is a confirmed anomaly (not just noise)."""
        if not self.fitted:
            raise RuntimeError("Call .fit() with clean baseline windows first")
        pred = self.model.predict(window_features.reshape(1, -1))[0]  # -1 = anomaly, 1 = normal
        return pred == -1


# ------------------------------------------------------------------
# LAYER 3 — TREND FORECAST (linear extrapolation, time-to-critical)
# ------------------------------------------------------------------

def forecast_days_to_critical(blockage_pct_history, timestamps_days, critical_threshold_pct=50.0):
    """
    Fits a straight line through blockage-% over time and projects forward
    to estimate how many days until this segment crosses a critical
    blockage threshold. Returns None if the trend is flat/improving
    (no forecast needed) or if there's not enough data yet.

    blockage_pct_history: list of blockage % readings over time
    timestamps_days: matching list of time (in days) each reading was taken
    """
    if len(blockage_pct_history) < 3:
        return None  # not enough data for a trustworthy trend

    y = np.array(blockage_pct_history, dtype=float)
    x = np.array(timestamps_days, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)

    if slope <= 0:
        return None  # blockage not worsening over time — no forecast needed

    # Solve: critical_threshold_pct = slope * t + intercept  ->  t = (threshold - intercept) / slope
    t_critical = (critical_threshold_pct - intercept) / slope
    days_from_now = t_critical - x[-1]
    if days_from_now < 0:
        return 0.0  # already past the threshold based on trend
    return round(days_from_now, 1)


# ------------------------------------------------------------------
# Self-test with synthetic data — proves the math is correct before
# you plug in real sensor readings.
# ------------------------------------------------------------------
if __name__ == "__main__":
    print(f"=== Hardware geometry ===")
    print(f"Drainage pipe diameter : {PIPE_DIAMETER_CM:.2f} cm")
    print(f"Drainage pipe area     : {PIPE_AREA_CM2:.4f} cm^2  (= pi × (d/2)^2)")
    print(f"Inlet box base area    : {INLET_BOX_BASE_AREA_CM2:.1f} cm^2")

    print("\n=== Testing calibration ===")
    # Example: pour 200 mL in 10 s, steady height 2 cm, clean area = PIPE_AREA_CM2
    # (using the real pipe area so self-test is grounded in the actual hardware)
    cd = calibrate_cd(pour_volume_ml=200, pour_time_sec=10, steady_h_cm=2.0, a_clean_cm2=PIPE_AREA_CM2)
    print(f"Calibrated Cd: {cd:.4f}")

    print("\n=== Testing clean-pipe detection (should show ~0% blocked) ===")
    q_test = 200 / 10  # same pour rate as calibration
    a_calc = calculate_area(q_test, cd, h_cm=2.0)
    pct = blockage_percent(a_calc, a_clean_cm2=PIPE_AREA_CM2)
    print(f"Calculated area: {a_calc:.4f} cm^2 (expected ~{PIPE_AREA_CM2:.4f}), blockage: {pct:.1f}%")

    print("\n=== Testing blocked-pipe detection (same inflow, higher water level) ===")
    # A blockage causes the same inflow to back up to a higher water level.
    # Simulate: height rises to 4 cm instead of 2 cm for the same Q.
    a_calc_blocked = calculate_area(q_test, cd, h_cm=4.0)
    pct_blocked = blockage_percent(a_calc_blocked, a_clean_cm2=PIPE_AREA_CM2)
    print(f"Calculated area: {a_calc_blocked:.4f} cm^2, blockage: {pct_blocked:.1f}%")

    print("\n=== Testing ML confirmation layer ===")
    # Simulate a proper-sized clean-baseline set (small noise around 0% blockage).
    # NOTE: 10 samples (an earlier version of this test) is too few for Isolation
    # Forest to learn a stable boundary — it needs enough examples of "normal"
    # variation to distinguish real anomalies from noise. In your real deployment,
    # this baseline would be built from your first several days/weeks of clean
    # (or known-recently-cleaned) readings.
    np.random.seed(42)
    clean_readings = [list(np.random.normal(0, 2, 5)) for _ in range(60)]
    clean_features = [extract_window_features(w) for w in clean_readings]

    detector = BlockageAnomalyDetector(contamination=0.05)
    detector.fit(clean_features)

    # Test 1: a normal noisy window (should NOT be flagged)
    normal_window = [1.2, -0.5, 0.8, 1.5, 0.3]
    normal_features = extract_window_features(normal_window)
    print(f"Normal window flagged as anomaly: {detector.is_confirmed_anomaly(normal_features)}")

    # Test 2: a sustained rising-blockage window (SHOULD be flagged)
    rising_window = [5, 15, 28, 40, 55]
    rising_features = extract_window_features(rising_window)
    print(f"Rising-blockage window flagged as anomaly: {detector.is_confirmed_anomaly(rising_features)}")

    print("\n=== Testing trend forecast ===")
    history = [2, 5, 9, 14, 20]  # blockage % over 5 readings
    days = [0, 1, 2, 3, 4]       # one reading per day
    forecast = forecast_days_to_critical(history, days, critical_threshold_pct=50.0)
    print(f"Days until 50% blockage (critical): {forecast}")

    print("\nAll self-tests ran without errors.")
