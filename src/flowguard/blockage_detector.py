"""
blockage_detector.py — FlowGuard core physics + ML detection engine.

All physics are computed in SI units (m, m², m³/s, m/s²) internally.
The public API accepts/returns cm or mL/s where noted for UI compatibility.

Detection architecture (three layers):

  1. PHYSICS (primary):
       Orifice equation Q_out = Cd·A·√(2·g·h) gives expected outflow.
       The residual between observed and predicted water-level rate is the
       primary blockage signal.  High water level alone is NOT evidence of
       blockage — only a *persistent deviation* from expected clear-drain
       hydraulic behaviour is.

  2. ML CONFIRMATION (secondary):
       Isolation Forest trained exclusively on NORMAL/clear-drain feature
       windows.  Used to confirm that a physics-flagged anomaly is a
       sustained pattern shift, not sensor noise.

  3. REVERSIBLE STATE MACHINE:
       NORMAL → POSSIBLE_BLOCKAGE → BLOCKAGE_CONFIRMED → CLEARING → NORMAL
       The machine evaluates CURRENT hydraulic behaviour every cycle.
       Historical events are logged but never force a permanently blocked
       state — the machine can return to NORMAL after the drain clears.
"""

from __future__ import annotations

import enum
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from sklearn.ensemble import IsolationForest

from config import (
    SENSOR_TO_BOTTOM_M,
    CONTAINER_HEIGHT_M,
    LAKE_AREA_M2,
    DRAIN_AREA_M2,
    DRAIN_CENTER_HEIGHT_M,
    GRAVITY_M_S2,
    CALIBRATED_CD,
    INFLOW_RATE_M3S,
    BLOCKAGE_ENTER_THRESHOLD,
    BLOCKAGE_EXIT_THRESHOLD,
    BLOCKAGE_CONFIRMATION_SAMPLES,
    CLEAR_CONFIRMATION_SAMPLES,
    MIN_CLEARING_DURATION,
    RESIDUAL_WINDOW_SIZE,
    MIN_VALID_HEAD_M,
    SENSOR_MIN_DIST_M,
    # legacy cm aliases kept for UI compatibility
    PIPE_DIAMETER_CM,
    PIPE_AREA_CM2,
    INLET_BOX_BASE_AREA_CM2,
)

# ---------------------------------------------------------------------------
# LAYER 1 — PHYSICS (orifice equation, all SI)
# ---------------------------------------------------------------------------

def sensor_distance_to_water_depth(sensor_distance_m: float) -> Optional[float]:
    """
    Convert raw ultrasonic reading to water depth above container bottom.

    sensor_distance_m: distance from sensor face to water surface (m).
    Returns water depth (m), or None if reading is physically impossible.
    """
    if sensor_distance_m < 0 or sensor_distance_m > SENSOR_TO_BOTTOM_M:
        return None   # impossible — reject as bad sensor reading
    if sensor_distance_m < SENSOR_MIN_DIST_M:
        return None   # spurious HC-SR04 short echo — container can't be this full
    return SENSOR_TO_BOTTOM_M - sensor_distance_m


def water_depth_to_hydraulic_head(water_depth_m: float) -> float:
    """
    Hydraulic head = water height above the CENTER of the drain opening.

    Returns h (m).  May be negative (drain submerged above water or box dry).
    Callers must check h > 0 before passing to orifice equation.
    """
    return water_depth_m - DRAIN_CENTER_HEIGHT_M


def expected_outflow(cd: float, h_m: float,
                     drain_area_m2: float = DRAIN_AREA_M2) -> float:
    """
    Orifice equation: Q_out = Cd · A · √(2·g·h)

    cd:           discharge coefficient (dimensionless)
    h_m:          hydraulic head above drain center (m); must be > 0
    drain_area_m2: effective drain cross-section (m²); use DRAIN_AREA_M2
                   for clean drain, DRAIN_AREA_M2*(1-blockage_fraction) for
                   blockage simulation only.
    Returns Q_out (m³/s).  Returns 0 if h_m <= 0.
    """
    if h_m <= 0:
        return 0.0
    return cd * drain_area_m2 * np.sqrt(2.0 * GRAVITY_M_S2 * h_m)


def predicted_level_rate(cd: float, h_m: float,
                          q_in_m3s: float = INFLOW_RATE_M3S) -> float:
    """
    Expected rate of change of water depth for a CLEAR drain (m/s).

    d(water_depth)/dt = (Q_in - Q_expected) / LAKE_AREA
    """
    q_out = expected_outflow(cd, h_m)
    return (q_in_m3s - q_out) / LAKE_AREA_M2


def next_water_depth(water_depth_m: float, cd: float, dt_s: float,
                      q_in_m3s: float = INFLOW_RATE_M3S) -> float:
    """
    Euler step for water level dynamics (m).

    water_depth_next = water_depth + (Q_in - Q_out) / LAKE_AREA * dt
    """
    h = water_depth_to_hydraulic_head(water_depth_m)
    q_out = expected_outflow(cd, h)
    d_depth = (q_in_m3s - q_out) / LAKE_AREA_M2 * dt_s
    return water_depth_m + d_depth


def is_overflow(water_depth_m: float) -> bool:
    """True when water depth has reached or exceeded the container rim."""
    return water_depth_m >= CONTAINER_HEIGHT_M


# ---------------------------------------------------------------------------
# Legacy cm-unit wrappers — kept for dashboard/serial_reader compatibility
# ---------------------------------------------------------------------------

def calibrate_cd(pour_volume_ml: float, pour_time_sec: float,
                 steady_h_cm: float, a_clean_cm2: float) -> float:
    """
    Calibrate Cd from a jug-pour experiment.  Inputs in cm/mL units.

    pour_volume_ml : total water poured (mL == cm³)
    pour_time_sec  : duration of pour (s)
    steady_h_cm    : steady-state water height in inlet box (cm)
    a_clean_cm2    : known clean pipe area (cm²)
    """
    if steady_h_cm <= 0:
        raise ValueError("steady_h_cm must be > 0")
    q_cm3s = pour_volume_ml / pour_time_sec   # cm³/s
    g_cm = 981.0                               # cm/s²
    return q_cm3s / (a_clean_cm2 * np.sqrt(2.0 * g_cm * steady_h_cm))


def calculate_area(q_cm3_s: float, cd: float, h_cm: float) -> Optional[float]:
    """
    Back-calculate effective open area from observed flow and head (cm units).
    Returns cm², or None if h_cm <= 0.
    """
    if h_cm <= 0:
        return None
    g_cm = 981.0
    denom = cd * np.sqrt(2.0 * g_cm * h_cm)
    if denom == 0:
        return None
    return q_cm3_s / denom


def blockage_percent(a_calculated_cm2: Optional[float],
                     a_clean_cm2: float) -> Optional[float]:
    """
    Blockage percentage from area comparison.
    Positive = capacity lost.  ~0 or negative = channel clear.
    """
    if a_calculated_cm2 is None:
        return None
    return (a_clean_cm2 - a_calculated_cm2) / a_clean_cm2 * 100.0


# ---------------------------------------------------------------------------
# LAYER 2 — RESIDUAL-BASED BLOCKAGE STATE MACHINE
# ---------------------------------------------------------------------------

class BlockageState(enum.Enum):
    NORMAL = "NORMAL"
    POSSIBLE_BLOCKAGE = "POSSIBLE_BLOCKAGE"
    BLOCKAGE_CONFIRMED = "BLOCKAGE_CONFIRMED"
    CLEARING = "CLEARING"


@dataclass
class SensorReading:
    """One validated sensor sample."""
    sensor_distance_m: float
    water_depth_m: float
    hydraulic_head_m: float
    q_out_expected_m3s: float
    level_rate_predicted: float  # m/s, for clear drain
    level_rate_observed: float   # m/s, estimated from consecutive readings
    residual: float              # observed_rate - predicted_rate (m/s)
    overflow: bool


@dataclass
class BlockageDetectorState:
    """
    Mutable state held between readings.  Pass this object into each call to
    process_reading() so state persists across multiple readings.

    Rolling window history and counters are stored here — NOT in module-level
    globals — so tests can create independent instances without interference.
    """
    cd: float = CALIBRATED_CD
    q_in_m3s: float = INFLOW_RATE_M3S

    # Current state-machine state
    state: BlockageState = BlockageState.NORMAL

    # Counters for hysteresis
    _above_enter_count: int = field(default=0, repr=False)
    _below_exit_count: int = field(default=0, repr=False)
    _clearing_count: int = field(default=0, repr=False)

    # Rolling residual window (deque of float residuals, m/s)
    _residual_window: deque = field(
        default_factory=lambda: deque(maxlen=RESIDUAL_WINDOW_SIZE), repr=False
    )

    # Previous water depth for level-rate estimation
    _prev_depth_m: Optional[float] = field(default=None, repr=False)

    # Feature history for Isolation Forest (list of feature arrays from NORMAL windows)
    _normal_features: list = field(default_factory=list, repr=False)
    _anomaly_detector: Optional["BlockageAnomalyDetector"] = field(default=None, repr=False)


def process_reading(state: BlockageDetectorState,
                    sensor_distance_m: float,
                    dt_s: float = 1.0) -> tuple[Optional[SensorReading], BlockageState]:
    """
    Main entry point.  Given a raw sensor distance (m) and time step,
    update the state machine and return (SensorReading | None, BlockageState).

    Returns (None, current_state) when the reading is physically invalid.
    The state machine is only advanced on valid readings.
    """
    # --- Sensor validation ---
    water_depth = sensor_distance_to_water_depth(sensor_distance_m)
    if water_depth is None:
        return None, state.state   # reject impossible reading

    h = water_depth_to_hydraulic_head(water_depth)
    q_out = expected_outflow(state.cd, h)
    pred_rate = predicted_level_rate(state.cd, h, state.q_in_m3s)
    overflow = is_overflow(water_depth)

    # Below minimum operating head the drain is barely/not submerged and
    # pred_rate = q_in/LAKE_AREA (~1.62 mm/s) while obs_rate ≈ 0 on a dry
    # channel.  HC-SR04 noise spikes (±3 mm) easily exceed the 0.2 mm/s
    # enter threshold, causing false BLOCKAGE_CONFIRMED with no water present.
    # Hold NORMAL and reset the blockage counter without advancing the machine.
    # Do NOT update _prev_depth_m: if we stored a sub-threshold depth here,
    # the first post-gate reading would compute a large obs_rate spike from
    # the artificially low previous depth, re-introducing false positives.
    if h < MIN_VALID_HEAD_M:
        state._above_enter_count = 0
        if state.state in (BlockageState.NORMAL, BlockageState.POSSIBLE_BLOCKAGE):
            state.state = BlockageState.NORMAL
        reading = SensorReading(
            sensor_distance_m=sensor_distance_m,
            water_depth_m=water_depth,
            hydraulic_head_m=h,
            q_out_expected_m3s=q_out,
            level_rate_predicted=pred_rate,
            level_rate_observed=0.0,
            residual=0.0,
            overflow=overflow,
        )
        return reading, state.state

    # --- Level rate estimation ---
    if state._prev_depth_m is not None:
        obs_rate = (water_depth - state._prev_depth_m) / dt_s
    else:
        obs_rate = pred_rate   # no previous reading yet; assume on-model

    state._prev_depth_m = water_depth

    residual = obs_rate - pred_rate
    state._residual_window.append(residual)

    reading = SensorReading(
        sensor_distance_m=sensor_distance_m,
        water_depth_m=water_depth,
        hydraulic_head_m=h,
        q_out_expected_m3s=q_out,
        level_rate_predicted=pred_rate,
        level_rate_observed=obs_rate,
        residual=residual,
        overflow=overflow,
    )

    # Use rolling SIGNED mean residual as the signal.
    #
    # Positive = water is rising faster than clear-drain physics predicts
    #            → blockage evidence.
    # Near zero = water is tracking the clear-drain model → normal.
    # Negative  = water is draining faster than predicted → definitely clearing.
    #
    # Using abs() would mean any residual (including correct-direction
    # drainage) accumulates as a positive signal, causing false blockages
    # when the drain is running at a depth away from steady state.
    if len(state._residual_window) >= 3:
        signal = float(np.mean(list(state._residual_window)))
    else:
        signal = residual

    # --- Collect features for Isolation Forest when in NORMAL state ---
    _maybe_update_anomaly_detector(state, reading)

    # --- State machine transitions ---
    state.state = _advance_state(state, signal)

    return reading, state.state


def _advance_state(state: BlockageDetectorState, signal: float) -> BlockageState:
    """
    Pure state-machine logic.  Advances based on the SIGNED rolling-mean
    residual and enter/exit thresholds with hysteresis.

    signal > BLOCKAGE_ENTER_THRESHOLD  =>  water rising faster than clear-drain
                                            physics predicts  →  blockage evidence
    signal < BLOCKAGE_EXIT_THRESHOLD   =>  water tracking or draining beyond
                                            model  →  normal / clearing evidence

    BLOCKAGE_EXIT_THRESHOLD < BLOCKAGE_ENTER_THRESHOLD so there is a dead-band
    between the two thresholds that prevents rapid oscillation.  The exit
    threshold may be zero or slightly negative (normal-to-clearing direction).
    """
    current = state.state

    if current == BlockageState.NORMAL:
        if signal > BLOCKAGE_ENTER_THRESHOLD:
            state._above_enter_count += 1
            state._below_exit_count = 0
        else:
            state._above_enter_count = 0
        if state._above_enter_count >= BLOCKAGE_CONFIRMATION_SAMPLES:
            state._above_enter_count = 0
            return BlockageState.POSSIBLE_BLOCKAGE
        return BlockageState.NORMAL

    elif current == BlockageState.POSSIBLE_BLOCKAGE:
        if signal > BLOCKAGE_ENTER_THRESHOLD:
            state._above_enter_count += 1
            state._below_exit_count = 0
        elif signal < BLOCKAGE_EXIT_THRESHOLD:
            state._below_exit_count += 1
            state._above_enter_count = 0
        # within dead-band: hold counts
        if state._above_enter_count >= BLOCKAGE_CONFIRMATION_SAMPLES:
            state._above_enter_count = 0
            state._below_exit_count = 0
            return BlockageState.BLOCKAGE_CONFIRMED
        if state._below_exit_count >= CLEAR_CONFIRMATION_SAMPLES:
            state._above_enter_count = 0
            state._below_exit_count = 0
            return BlockageState.NORMAL
        return BlockageState.POSSIBLE_BLOCKAGE

    elif current == BlockageState.BLOCKAGE_CONFIRMED:
        if signal < BLOCKAGE_EXIT_THRESHOLD:
            state._below_exit_count += 1
            state._above_enter_count = 0
        else:
            state._below_exit_count = 0
        if state._below_exit_count >= CLEAR_CONFIRMATION_SAMPLES:
            state._below_exit_count = 0
            state._clearing_count = 0
            return BlockageState.CLEARING
        return BlockageState.BLOCKAGE_CONFIRMED

    elif current == BlockageState.CLEARING:
        state._clearing_count += 1
        if signal > BLOCKAGE_ENTER_THRESHOLD:
            state._above_enter_count += 1
            if state._above_enter_count >= BLOCKAGE_CONFIRMATION_SAMPLES:
                state._above_enter_count = 0
                state._clearing_count = 0
                return BlockageState.BLOCKAGE_CONFIRMED
        else:
            state._above_enter_count = 0

        if (state._clearing_count >= MIN_CLEARING_DURATION and
                signal < BLOCKAGE_EXIT_THRESHOLD):
            state._clearing_count = 0
            return BlockageState.NORMAL
        return BlockageState.CLEARING

    return current  # unreachable fallback


# ---------------------------------------------------------------------------
# LAYER 3 — ML CONFIRMATION (Isolation Forest, secondary layer)
# ---------------------------------------------------------------------------

def extract_window_features(blockage_pct_series) -> Optional[np.ndarray]:
    """
    Extract pattern features from a rolling window of blockage-% readings.
    Returns [mean, slope, std] as a 1-D array, or None if too few samples.
    """
    arr = np.array(blockage_pct_series, dtype=float)
    if len(arr) < 2:
        return None
    x = np.arange(len(arr), dtype=float)
    slope = float(np.polyfit(x, arr, 1)[0])
    return np.array([float(arr.mean()), slope, float(arr.std())])


def extract_residual_features(state: BlockageDetectorState) -> Optional[np.ndarray]:
    """
    Richer feature vector drawn from rolling residual history.
    Intended as input to the Isolation Forest.

    Features:
        water_depth, hydraulic_head, obs_level_rate, pred_level_rate,
        residual, rolling_mean_residual, rolling_std_residual, residual_trend
    """
    win = list(state._residual_window)
    if len(win) < 3:
        return None
    arr = np.array(win, dtype=float)
    x = np.arange(len(arr), dtype=float)
    trend = float(np.polyfit(x, arr, 1)[0])
    return np.array([
        float(np.mean(arr)),
        float(np.std(arr)),
        trend,
        float(np.mean(np.abs(arr))),
    ])


class BlockageAnomalyDetector:
    """
    Isolation Forest trained on NORMAL (clear-drain) feature windows.

    The model is fit once on clean baseline data.  After that, call
    is_confirmed_anomaly() to check whether a new feature window is
    statistically consistent with normal behaviour.

    Direction of predict() / score_samples():
        predict()       returns  1 = normal,  -1 = anomaly
        score_samples() returns negative scores for anomalies
                        (less negative == more normal)
    """

    def __init__(self, contamination: float = 0.1):
        self.model = IsolationForest(contamination=contamination,
                                     random_state=42)
        self.fitted = False

    def fit(self, clean_windows_features: list) -> None:
        """
        clean_windows_features: list of 1-D feature arrays from
        extract_window_features() or extract_residual_features(),
        all drawn from NORMAL / clear-drain conditions.
        """
        X = np.array(clean_windows_features)
        self.model.fit(X)
        self.fitted = True

    def is_confirmed_anomaly(self, window_features: np.ndarray) -> bool:
        """
        Returns True when features are anomalous relative to clean baseline.
        predict() == -1  means  outside the normal distribution.
        """
        if not self.fitted:
            raise RuntimeError("Call .fit() with clean baseline windows first")
        pred = self.model.predict(window_features.reshape(1, -1))[0]
        return bool(pred == -1)

    def anomaly_score(self, window_features: np.ndarray) -> float:
        """
        Returns the raw anomaly score from score_samples().
        More negative = more anomalous.  Normal samples are near 0.
        """
        if not self.fitted:
            raise RuntimeError("Call .fit() with clean baseline windows first")
        return float(self.model.score_samples(window_features.reshape(1, -1))[0])


def _maybe_update_anomaly_detector(state: BlockageDetectorState,
                                    reading: SensorReading) -> None:
    """
    When the state machine is NORMAL, collect residual feature vectors for
    the Isolation Forest baseline.  Refit the model periodically.
    Only NORMAL-state windows are added so the model learns clear-drain
    behaviour, not blockage behaviour.
    """
    if state.state != BlockageState.NORMAL:
        return
    feats = extract_residual_features(state)
    if feats is None:
        return
    state._normal_features.append(feats)
    # Refit every 10 new normal samples (once we have at least 20 total)
    n = len(state._normal_features)
    if n >= 20 and n % 10 == 0:
        if state._anomaly_detector is None:
            state._anomaly_detector = BlockageAnomalyDetector(contamination=0.1)
        state._anomaly_detector.fit(state._normal_features)


def ml_confirm_anomaly(state: BlockageDetectorState,
                        reading: SensorReading) -> bool:
    """
    Secondary ML check.  Returns True only when the detector has been
    fitted AND the current feature vector is outside normal bounds.
    Returns False (not confirmed) when insufficient data.
    """
    if state._anomaly_detector is None or not state._anomaly_detector.fitted:
        return False
    feats = extract_residual_features(state)
    if feats is None:
        return False
    return state._anomaly_detector.is_confirmed_anomaly(feats)


# ---------------------------------------------------------------------------
# LAYER 4 — TREND FORECAST (unchanged API, kept for UI)
# ---------------------------------------------------------------------------

def forecast_days_to_critical(blockage_pct_history: list,
                               timestamps_days: list,
                               critical_threshold_pct: float = 50.0
                               ) -> Optional[float]:
    """
    Linear extrapolation of blockage % trend.
    Returns days until critical threshold, or None if trend is flat/improving.
    """
    if len(blockage_pct_history) < 3:
        return None
    y = np.array(blockage_pct_history, dtype=float)
    x = np.array(timestamps_days, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    if slope <= 0:
        return None
    t_critical = (critical_threshold_pct - intercept) / slope
    days_from_now = t_critical - x[-1]
    return 0.0 if days_from_now < 0 else round(days_from_now, 1)
