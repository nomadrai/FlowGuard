"""
blockage_detector.py — FlowGuard's core physics + ML detection engine.

Detection is RATE-BASED, not level-based. A blockage is NOT "water above
height X" — it is "water rising much faster than the recent normal rainfall
rise rate". The system learns the normal rise rate from history and only
flags unusual accelerations above it:

    rise_rate > normal_rise_rate + threshold  ->  blockage
    water level decreasing                     ->  clear (blockage opened)

Four layers:
  1. PHYSICS: orifice equation (from Bernoulli) — converts live water height
     readings into a calculated open channel area (used for calibration and
     the audit-trail blockage-% estimate; verdicts do NOT rely on it).
  2. RATE-BASED VERDICT: rolling-window slopes of water level vs. a robust
     (median) baseline of the normal rise rate. Handles noise from the
     HC-SR04 (±0.3 cm) by averaging over windows instead of per-reading diffs.
  3. ML CONFIRMATION: a single noisy reading doesn't mean much (a splash,
     a sensor glitch). We keep a rolling window of water-level behaviour,
     extract rate features (rise rate, acceleration, rate ratio vs
     baseline), and run an Isolation Forest trained on KNOWN-CLEAN behaviour
     to decide whether a sustained pattern is a real anomaly — not just
     point-in-time noise.
  4. TREND FORECAST: linear regression on blockage-% over time, projected
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
# LAYER 2 — RATE-BASED BLOCKAGE VERDICT (the primary detection signal)
# ------------------------------------------------------------------
#
# A blockage is a CHANGE in how fast the water is rising, never an absolute
# water level. The sensor noise floor (~±0.3 cm on the HC-SR04) means single
# reading-to-reading differences are too noisy to trust, so rates are
# least-squares slopes over rolling windows of readings.

RATE_RECENT_WINDOW = 10      # readings in the "current" slope window
RATE_BASELINE_WINDOW = 10    # readings per slope sample in the baseline history
RATE_MIN_READINGS = 20       # readings needed before a verdict is meaningful
RATE_ABS_MARGIN = 0.05       # cm/reading: minimum margin above baseline to flag
RATE_MULTIPLIER = 0.8        # margin also scales with the baseline itself
RATE_FALL_THRESHOLD = 0.0    # rate at/below this (cm/reading) => level falling
RATE_CLEAR_HYSTERESIS = 0.5  # fraction of margin: rate within this of baseline => clear

# Reference-height tolerance: ±0.5 cm defines "stable" and "reverted to
# reference" (matches the HC-SR04 noise floor).
REF_TOLERANCE_CM = 0.5
REF_LARGE_DROP_CM = 1.5      # drop beyond this needs only 5 readings to confirm
REF_STABLE_READINGS = 7      # consecutive in-band readings to re-baseline
REF_LARGE_READINGS = 5       # consecutive large-drop readings to re-baseline

# Final-gate filter: CLEAR is declared only after this many CONSECUTIVE
# decreasing sensor readings. A single/isolated sudden decrease (HC-SR04
# glitch) must never clear a live blockage.
CLEAR_CONSECUTIVE_DECREASES = 3


def _slope(values):
    """Least-squares slope of a series (rate per reading step)."""
    x = np.arange(len(values))
    return float(np.polyfit(x, values, 1)[0])


def _rolling_slopes(levels, window):
    """Slope of every window of `window` consecutive readings."""
    return [_slope(levels[i:i + window]) for i in range(len(levels) - window + 1)]


def detect_blockage_from_rise(water_levels, times=None,
                              recent_window=RATE_RECENT_WINDOW,
                              baseline_window=RATE_BASELINE_WINDOW,
                              min_readings=RATE_MIN_READINGS,
                              abs_margin=RATE_ABS_MARGIN,
                              multiplier=RATE_MULTIPLIER,
                              fall_threshold=RATE_FALL_THRESHOLD,
                              clear_hysteresis=RATE_CLEAR_HYSTERESIS):
    """
    RATE-BASED blockage verdict — the primary detection signal.

    Learns the normal (rainfall) rise rate from the earlier history and flags
    only unusual accelerations above it. An absolute water level NEVER decides
    the verdict.

        blockage: current_rate > baseline_rate + max(abs_margin, multiplier * baseline_rate)
        clear:    current_rate <= baseline_rate + clear_hysteresis * margin  (rate back near normal)
                  OR current_rate <= fall_threshold                          (level falling = cleared)

    Args:
        water_levels: list of water levels (cm), oldest -> newest.
        times: optional matching times (any units, e.g. seconds) — used only
            for slope rescaling; None means one reading per step.
        recent_window: readings used to estimate the CURRENT rise rate.
        baseline_window: readings per slope sample used to learn the normal
            (rainfall) rise rate. Smaller = more responsive to drift.
        min_readings: readings required before the verdict is meaningful.
        abs_margin: minimum margin (cm/reading) above baseline to flag.
        multiplier: baseline scales the margin too (relative acceleration).
        fall_threshold: rate at/below this counts as "water falling".
        clear_hysteresis: fraction of the margin — the current rate may sit
            this close to baseline and still be CLEAR (prevents chattering).

    Returns:
        dict with verdict ("CLEAR" | "BLOCKAGE_DETECTED"), current_rate,
        baseline_rate, margin, and reason (why the verdict was chosen).
    """
    levels = [float(h) for h in water_levels if h is not None and np.isfinite(h) and h >= 0]
    scale = 1.0
    if times is not None:
        times = [float(t) for t in times if t is not None]
        if len(times) != len(levels) or len(times) < 2:
            times = None
        else:
            dt = times[-1] - times[0]
            scale = len(levels) / dt if dt > 0 else 1.0  # per-step -> per-time-unit

    n = len(levels)
    if n < min_readings or n < recent_window + baseline_window:
        return {
            "verdict": "CLEAR",
            "current_rate": None,
            "baseline_rate": None,
            "margin": None,
            "reason": "insufficient data — establishing the normal rise-rate baseline",
        }

    # Current rise rate: slope over the most recent readings.
    current_rate = _slope(levels[-recent_window:]) * scale

    # Normal rise rate: median of every rolling-window slope BEFORE the
    # recent window — the learned "rainfall" behaviour.
    baseline_slopes = _rolling_slopes(levels[:-recent_window], baseline_window)
    baseline_rate = float(np.median(baseline_slopes)) * scale if baseline_slopes else 0.0

    # Rate-based margin: a minimum absolute cushion PLUS a relative cushion
    # that grows with the normal rise rate itself.
    margin = max(abs_margin * scale, multiplier * max(baseline_rate, 0.0))

    if current_rate <= fall_threshold:
        verdict = "CLEAR"
        reason = "water level falling — blockage has been cleared/opened"
    elif current_rate > baseline_rate + margin:
        verdict = "BLOCKAGE_DETECTED"
        reason = "rise rate far above the normal rainfall rise rate"
    elif current_rate <= baseline_rate + clear_hysteresis * margin:
        verdict = "CLEAR"
        reason = "rise rate back to the normal rainfall rate"
    else:
        verdict = "BLOCKAGE_DETECTED"
        reason = "rise rate still elevated above the normal rainfall rate"

    return {
        "verdict": verdict,
        "current_rate": round(current_rate, 4),
        "baseline_rate": round(baseline_rate, 4),
        "margin": round(margin, 4),
        "reason": reason,
    }


class ReferenceHeightTracker:
    """
    Tracks the reference water level and re-baselines it ONLY on genuine
    decreases (blockage cleared / pipe opened) — never on rises, which are
    exactly what a blockage does.

    Events returned by update():
      None                     — normal reading, nothing confirmed yet
      "STABLE_LEVEL_CONFIRMED" — small decrease held stable within ±0.5 cm
                                 for 7 consecutive readings
      "LARGE_DECREASE_CONFIRMED" — drop > 1.5 cm held for 5 consecutive readings
    """

    def __init__(self, initial_fixed_height_cm=None):
        self.fixed_height = initial_fixed_height_cm
        self.decrease_detected = False
        self._candidate = None        # level the water settled at after a drop
        self._stable_count = 0        # consecutive in-band readings since the drop
        self._large_count = 0         # consecutive large-drop readings

    def update(self, water_level_cm):
        """
        Feed one valid reading (cm). Returns an event string or None.
        Invalid readings (None or <= 0) are ignored.
        """
        if water_level_cm is None or water_level_cm <= 0:
            return None

        if self.fixed_height is None:
            # Startup: the first reading is the reference.
            self.fixed_height = float(water_level_cm)
            return None

        drop = self.fixed_height - water_level_cm

        # Back within tolerance of the old reference -> the decrease was
        # only a transient dip; abort re-baselining.
        if abs(drop) <= REF_TOLERANCE_CM:
            self.decrease_detected = False
            self._candidate = None
            self._stable_count = 0
            self._large_count = 0
            return None

        if drop > 0:
            # Water is below the reference — a decrease is in progress.
            self.decrease_detected = True
            if self._candidate is None:
                # Trigger reading: it is streak #1 by definition (the drop is
                # already past tolerance), so record it and wait for more.
                self._candidate = float(water_level_cm)
                self._stable_count = 1
                self._large_count = 1 if drop > REF_LARGE_DROP_CM else 0
                return None

            if drop > REF_LARGE_DROP_CM:
                # Large drop: confirm after 5 consecutive readings.
                self._large_count += 1
                if self._large_count >= REF_LARGE_READINGS:
                    self.fixed_height = float(water_level_cm)
                    self.decrease_detected = False
                    self._candidate = None
                    self._stable_count = 0
                    self._large_count = 0
                    return "LARGE_DECREASE_CONFIRMED"
            else:
                self._large_count = 0
                # Small drop: confirm only when the new level holds steady
                # within ±0.5 cm of the candidate for 7 consecutive readings.
                if abs(water_level_cm - self._candidate) <= REF_TOLERANCE_CM:
                    self._stable_count += 1
                    if self._stable_count >= REF_STABLE_READINGS:
                        self.fixed_height = float(self._candidate)
                        self.decrease_detected = False
                        self._candidate = None
                        self._stable_count = 0
                        self._large_count = 0
                        return "STABLE_LEVEL_CONFIRMED"
                else:
                    self._stable_count = 0
            return None

        # Water is above the reference (rise): never re-baseline — a rise is
        # a possible blockage, not a new reference. A rise also aborts any
        # pending decrease confirmation: the dip was only transient.
        self.decrease_detected = False
        self._candidate = None
        self._stable_count = 0
        self._large_count = 0
        return None


class ClearConfirmationFilter:
    """
    Final gate on the CLEAR status — sits ABOVE the rate verdict, the ML
    confirmation, and the reference-height tracker.

    Once the pipeline below has flagged a blockage, CLEAR is declared only
    after CLEAR_CONSECUTIVE_DECREASES consecutive decreasing sensor
    readings. A single/isolated sudden decrease — a sensor glitch, not a
    cleared blockage — never clears a live blockage, no matter what the
    verdict/ML logic says.

    Usage: feed EVERY valid reading via update(h, raw_blocked), where
    raw_blocked is the blockage verdict of the pipeline below this filter
    (rate verdict, ML, reference tracker). update() returns the final,
    filtered status: "BLOCKAGE DETECTED" | "CLEAR".
    """

    def __init__(self, required_decreases=CLEAR_CONSECUTIVE_DECREASES):
        self.required_decreases = required_decreases
        self.blocked = False  # latched blockage state — only 3 consecutive decreases clear it
        self._consecutive_decreases = 0
        self._last_level = None

    def update(self, water_level_cm, raw_blocked):
        """
        Feed one valid reading (cm) plus the raw pipeline verdict for it.
        Returns the final, filtered status ("BLOCKAGE DETECTED" | "CLEAR").
        """
        if self._last_level is None:
            self._last_level = float(water_level_cm)
        elif water_level_cm < self._last_level:
            self._consecutive_decreases += 1
        else:
            self._consecutive_decreases = 0  # any rise/plateau resets the streak
        self._last_level = float(water_level_cm)

        if raw_blocked:
            self.blocked = True
            return "BLOCKAGE DETECTED"
        if self.blocked and self._consecutive_decreases < self.required_decreases:
            return "BLOCKAGE DETECTED"  # decrease not yet sustained — sensor noise
        self.blocked = False
        return "CLEAR"


# ------------------------------------------------------------------
# LAYER 3 — ML CONFIRMATION (Isolation Forest on rolling windows)
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


def extract_rate_features(water_levels, times=None, baseline_rate=None):
    """
    Features for the Isolation Forest, describing WATER-LEVEL RATE BEHAVIOUR
    rather than absolute level:
      - rate:        current rise rate (cm per reading / per time unit)
      - accel:       change in the rise rate (second slope) — a blockage
                     accelerates the rise
      - rate_ratio:  current rise rate vs the NORMAL rise rate — the main
                     signal. Pass the learned baseline (median of the
                     normal rainfall rise rates); otherwise falls back to
                     the window's own mean rate.

    The absolute water level is deliberately NOT a feature: it has far more
    variance than the rate signals and would dominate the Isolation Forest's
    splits, hiding exactly the rate anomalies we must detect.

    Args:
        water_levels: list of water levels (cm), oldest -> newest.
        times: optional matching times; None means one reading per step.
        baseline_rate: the learned normal (rainfall) rise rate — the ratio
            feature compares the current rate against it.
    """
    levels = [float(h) for h in water_levels if h is not None and np.isfinite(h) and h >= 0]
    if len(levels) < 3:
        return None
    scale = 1.0
    if times is not None:
        times = [float(t) for t in times if t is not None]
        if len(times) == len(levels) and len(times) >= 2:
            dt = times[-1] - times[0]
            if dt > 0:
                scale = len(levels) / dt
    x = np.arange(len(levels))
    rate = np.polyfit(x, levels, 1)[0] * scale
    # Acceleration: slope of the rolling per-step differences.
    diffs = np.diff(levels)
    accel = np.polyfit(x[:-1], diffs, 1)[0] * scale
    if baseline_rate is not None and baseline_rate > 1e-9:
        rate_ratio = float(rate / baseline_rate)
    else:
        mean_rate = float(np.mean(diffs)) * scale
        rate_ratio = float(rate / mean_rate) if abs(mean_rate) > 1e-9 else 0.0
    return np.array([rate, accel, rate_ratio])


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
# LAYER 4 — TREND FORECAST (linear extrapolation, time-to-critical)
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

    print("\n=== Testing ML confirmation layer (rate features) ===")
    # Baseline: windows of steady normal rainfall rise (rate ~1 per step).
    np.random.seed(42)
    base = np.arange(30, dtype=float)
    baseline_rate = 1.0  # the learned normal rise rate
    clean_windows = [
        list(base + np.random.normal(0, 0.3, 30)) for _ in range(60)
    ]
    clean_features = [extract_rate_features(w, baseline_rate=baseline_rate) for w in clean_windows]

    detector = BlockageAnomalyDetector(contamination=0.05)
    detector.fit(clean_features)

    # Test 1: a normal noisy rise window (should NOT be flagged)
    normal_window = list(base + np.random.normal(0, 0.3, 30))
    normal_features = extract_rate_features(normal_window, baseline_rate=baseline_rate)
    print(f"Normal rise window flagged as anomaly: {detector.is_confirmed_anomaly(normal_features)}")

    # Test 2: a window where the rise accelerates sharply (SHOULD be flagged)
    rising_window = list(base) + [30 + 2.5 * i for i in range(10)]
    rising_features = extract_rate_features(rising_window, baseline_rate=baseline_rate)
    print(f"Accelerating-rise window flagged as anomaly: {detector.is_confirmed_anomaly(rising_features)}")

    print("\n=== Testing RATE-BASED verdict (the primary detection signal) ===")
    # Normal rainfall rise: ~1 cm per reading, with HC-SR04-scale noise.
    def noise():
        return float(np.random.normal(0, 0.15))

    normal_rise = [0.0] + [sum(1.0 + noise() for _ in range(i)) for i in range(1, 40)]
    normal_rise += [normal_rise[-1] + 1.0 + noise() for _ in range(10)]  # steady 1.0-1.1 range
    r = detect_blockage_from_rise(normal_rise)
    print(f"Normal rise (+1 cm/reading steady): {r['verdict']}  (expected CLEAR)  [{r['reason']}]")

    # Blockage: the rise suddenly accelerates to ~+2.5, then ~+3 cm/reading.
    blocked_rise = list(normal_rise)
    for _ in range(5):
        blocked_rise.append(blocked_rise[-1] + 2.5 + noise())
    for _ in range(5):
        blocked_rise.append(blocked_rise[-1] + 3.0 + noise())
    r = detect_blockage_from_rise(blocked_rise)
    print(f"Accelerating rise (+2.5, +3 cm/reading): {r['verdict']}  (expected BLOCKAGE_DETECTED)  "
          f"[current={r['current_rate']}, baseline={r['baseline_rate']}, reason: {r['reason']}]")

    # Blockage cleared: the water starts falling.
    clearing_rise = list(blocked_rise)
    for _ in range(3):
        clearing_rise.append(clearing_rise[-1] + 2.0 + noise())
    for _ in range(3):
        clearing_rise.append(clearing_rise[-1] + 0.5 + noise())
    for _ in range(5):
        clearing_rise.append(clearing_rise[-1] - 0.5 + noise())
    r = detect_blockage_from_rise(clearing_rise)
    print(f"Water falling (blockage opened): {r['verdict']}  (expected CLEAR)  [{r['reason']}]")

    # Insufficient data: first readings should never alarm.
    r = detect_blockage_from_rise([1.0, 1.1, 1.2, 1.3])
    print(f"Early data (4 readings): {r['verdict']}  (expected CLEAR)  [{r['reason']}]")

    print("\n=== Testing ReferenceHeightTracker (decrease -> clear + re-baseline) ===")
    tracker = ReferenceHeightTracker(initial_fixed_height_cm=20.0)
    tracker.update(20.0)
    tracker.update(18.8)  # decrease starts
    events = [tracker.update(18.9) for _ in range(6)]
    print(f"Small decrease re-baselined: {events[-1]} (expected STABLE_LEVEL_CONFIRMED), "
          f"fixed height now {tracker.fixed_height:.1f} cm")
    tracker2 = ReferenceHeightTracker(initial_fixed_height_cm=20.0)
    tracker2.update(20.0)
    events2 = [tracker2.update(18.2) for _ in range(5)]
    print(f"Large decrease re-baselined: {events2[-1]} (expected LARGE_DECREASE_CONFIRMED), "
          f"fixed height now {tracker2.fixed_height:.1f} cm")

    print("\n=== Testing ClearConfirmationFilter (3 consecutive decreases required) ===")
    f = ClearConfirmationFilter()
    # Blockage active: isolated dips must never clear it.
    assert f.update(5.0, True) == "BLOCKAGE DETECTED"
    assert f.update(5.2, True) == "BLOCKAGE DETECTED"
    assert f.update(4.1, False) == "BLOCKAGE DETECTED"  # dip #1 — ignored
    assert f.update(5.3, True) == "BLOCKAGE DETECTED"
    assert f.update(4.2, False) == "BLOCKAGE DETECTED"  # another isolated dip — ignored
    assert f.update(5.4, True) == "BLOCKAGE DETECTED"
    # Genuine clearing: 3 consecutive decreasing readings confirm CLEAR.
    assert f.update(4.6, False) == "BLOCKAGE DETECTED"  # decrease 1
    assert f.update(4.2, False) == "BLOCKAGE DETECTED"  # decrease 2
    assert f.update(3.9, False) == "CLEAR"              # decrease 3 -> confirmed
    assert f.update(3.8, False) == "CLEAR"              # streak continues
    print("Isolated dips ignored; CLEAR confirmed only after 3 consecutive decreases.")

    print("\n=== Testing trend forecast ===")
    history = [2, 5, 9, 14, 20]  # blockage % over 5 readings
    days = [0, 1, 2, 3, 4]       # one reading per day
    forecast = forecast_days_to_critical(history, days, critical_threshold_pct=50.0)
    print(f"Days until 50% blockage (critical): {forecast}")

    print("\nAll self-tests ran without errors.")
