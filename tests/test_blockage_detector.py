"""
test_blockage_detector.py — comprehensive regression tests for FlowGuard's
physics engine, state machine, and ML confirmation layer.

Test inventory (mirrors the required-tests list in the spec):
  1.  Unit conversions (cm → m, mL/s → m³/s)
  2.  sensor_distance → water_depth → hydraulic_head pipeline
  3.  h <= 0 gives Q_out = 0
  4.  Orifice equation sanity check
  5.  Dynamic water-level equation (Euler step)
  6.  Overflow detection at 7.5 cm
  7.  Clear drain does NOT immediately trigger blockage
  8.  Synthetic blockage produces persistent physics residual
  9.  Sensor noise does not cause false blockage
 10.  Isolation Forest correctly classifies normal vs anomalous samples
 11.  NORMAL → BLOCKED → UNBLOCKED → CLEARING → NORMAL
 12.  After returning to NORMAL, second blockage is detectable
 13.  Stale anomaly history does not keep state BLOCKED
 14.  Isolation Forest score direction (normal scores > anomaly scores)
"""

import sys
import os

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "flowguard"))

from flowguard.blockage_detector import (
    sensor_distance_to_water_depth,
    water_depth_to_hydraulic_head,
    expected_outflow,
    predicted_level_rate,
    next_water_depth,
    is_overflow,
    calibrate_cd,
    calculate_area,
    blockage_percent,
    BlockageDetectorState,
    BlockageState,
    process_reading,
    BlockageAnomalyDetector,
    extract_window_features,
)
from flowguard.config import (
    SENSOR_TO_BOTTOM_M,
    CONTAINER_HEIGHT_M,
    DRAIN_AREA_M2,
    GRAVITY_M_S2,
    CALIBRATED_CD,
    INFLOW_RATE_M3S,
    LAKE_AREA_M2,
    DRAIN_CENTER_HEIGHT_M,
    BLOCKAGE_CONFIRMATION_SAMPLES,
    CLEAR_CONFIRMATION_SAMPLES,
    MIN_CLEARING_DURATION,
    BLOCKAGE_ENTER_THRESHOLD,
    BLOCKAGE_EXIT_THRESHOLD,
    RESIDUAL_WINDOW_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _steady_state_depth() -> float:
    """
    Analytically compute the clear-drain steady-state depth where Q_in = Q_out.

    Q_in = Cd * A * sqrt(2*g*h_ss)
    =>  h_ss = (Q_in / (Cd*A))^2 / (2*g)
    =>  depth_ss = h_ss + DRAIN_CENTER_HEIGHT_M
    """
    h_ss = (INFLOW_RATE_M3S / (CALIBRATED_CD * DRAIN_AREA_M2)) ** 2 / (2.0 * GRAVITY_M_S2)
    return h_ss + DRAIN_CENTER_HEIGHT_M


def _sensor_dist(depth_m: float) -> float:
    """sensor distance corresponding to a given water depth."""
    return SENSOR_TO_BOTTOM_M - depth_m


def _simulate_clear_drain(det: BlockageDetectorState, n_steps: int,
                           start_depth: float = None, dt_s: float = 1.0) -> BlockageState:
    """
    Simulate n_steps of dynamically-evolving clear-drain readings.
    Water depth is updated via the Euler step each iteration so the
    simulated level actually converges to steady state, keeping residuals
    near zero (not artificially positive from constant-depth obs_rate=0).
    """
    depth = start_depth if start_depth is not None else _steady_state_depth()
    state = det.state
    for _ in range(n_steps):
        dist = _sensor_dist(depth)
        _, state = process_reading(det, dist, dt_s=dt_s)
        depth = next_water_depth(depth, det.cd, dt_s=dt_s, q_in_m3s=det.q_in_m3s)
        depth = max(0.001, min(depth, CONTAINER_HEIGHT_M - 0.001))
    return state


def _simulate_blockage(det: BlockageDetectorState, n_steps: int,
                        blockage_fraction: float = 0.85, dt_s: float = 1.0) -> BlockageState:
    """
    Simulate n_steps of blocked-drain readings.
    Outflow is reduced by blockage_fraction so water level rises.
    """
    depth = _steady_state_depth()
    state = det.state
    for _ in range(n_steps):
        dist = _sensor_dist(depth)
        _, state = process_reading(det, dist, dt_s=dt_s)
        h = water_depth_to_hydraulic_head(depth)
        q_out = expected_outflow(det.cd, max(h, 0.0),
                                  DRAIN_AREA_M2 * (1.0 - blockage_fraction))
        depth += (det.q_in_m3s - q_out) / LAKE_AREA_M2 * dt_s
        depth = max(0.001, min(depth, CONTAINER_HEIGHT_M - 0.001))
    return state


def _drive_to_confirmed(det: BlockageDetectorState,
                         max_steps: int = 300,
                         blockage_fraction: float = 0.85,
                         dt_s: float = 1.0) -> bool:
    """
    Drive detector to BLOCKAGE_CONFIRMED; return True if reached.

    Maintains a persistent 'depth' variable across all steps so the
    blocked-drain water level actually accumulates between readings
    (it must not be reset to steady-state on every step).
    """
    depth = _steady_state_depth()
    for _ in range(max_steps):
        dist = _sensor_dist(depth)
        process_reading(det, dist, dt_s=dt_s)
        if det.state == BlockageState.BLOCKAGE_CONFIRMED:
            return True
        # Advance depth with reduced effective outflow
        h = water_depth_to_hydraulic_head(depth)
        q_out = expected_outflow(det.cd, max(h, 0.0),
                                  DRAIN_AREA_M2 * (1.0 - blockage_fraction))
        depth += (det.q_in_m3s - q_out) / LAKE_AREA_M2 * dt_s
        depth = max(0.001, min(depth, CONTAINER_HEIGHT_M - 0.001))
    return False


def _drive_to_normal_after_blockage(det: BlockageDetectorState,
                                     max_steps: int = 400,
                                     dt_s: float = 1.0) -> bool:
    """
    Drive detector back to NORMAL from BLOCKAGE_CONFIRMED / CLEARING
    by simulating clear-drain dynamics long enough for the rolling
    residual window to flush and confirm normal behaviour.
    """
    depth = _steady_state_depth()
    for _ in range(max_steps):
        dist = _sensor_dist(depth)
        process_reading(det, dist, dt_s=dt_s)
        if det.state == BlockageState.NORMAL:
            return True
        depth = next_water_depth(depth, det.cd, dt_s=dt_s, q_in_m3s=det.q_in_m3s)
        depth = max(0.001, min(depth, CONTAINER_HEIGHT_M - 0.001))
    return False


# ---------------------------------------------------------------------------
# 1. Unit conversions
# ---------------------------------------------------------------------------

def test_unit_conversion_depth_from_sensor():
    dist_m = 0.08
    depth = sensor_distance_to_water_depth(dist_m)
    assert depth is not None
    assert abs(depth - (SENSOR_TO_BOTTOM_M - dist_m)) < 1e-9


def test_unit_conversion_inflow_si():
    """50 mL/s == 5e-5 m³/s."""
    assert abs(INFLOW_RATE_M3S - 5.0e-5) < 1e-12


def test_unit_conversion_drain_area():
    """DRAIN_AREA_M2 ≈ 2.83e-4 m²."""
    assert abs(DRAIN_AREA_M2 - 2.83e-4) < 1e-6


# ---------------------------------------------------------------------------
# 2. sensor_distance → water_depth → hydraulic_head
# ---------------------------------------------------------------------------

def test_sensor_to_depth_to_head_pipeline():
    dist_m = 0.10
    depth = sensor_distance_to_water_depth(dist_m)
    assert depth is not None
    assert abs(depth - (SENSOR_TO_BOTTOM_M - dist_m)) < 1e-9

    h = water_depth_to_hydraulic_head(depth)
    assert abs(h - (depth - DRAIN_CENTER_HEIGHT_M)) < 1e-9


def test_invalid_sensor_distance_rejected():
    assert sensor_distance_to_water_depth(-0.01) is None
    assert sensor_distance_to_water_depth(SENSOR_TO_BOTTOM_M + 0.001) is None


def test_zero_sensor_distance_edge():
    depth = sensor_distance_to_water_depth(0.0)
    assert depth is not None
    assert abs(depth - SENSOR_TO_BOTTOM_M) < 1e-9


# ---------------------------------------------------------------------------
# 3. h <= 0 → Q_out = 0
# ---------------------------------------------------------------------------

def test_zero_head_gives_zero_outflow():
    assert expected_outflow(CALIBRATED_CD, 0.0) == 0.0
    assert expected_outflow(CALIBRATED_CD, -0.05) == 0.0


def test_positive_head_gives_positive_outflow():
    assert expected_outflow(CALIBRATED_CD, 0.02) > 0


# ---------------------------------------------------------------------------
# 4. Orifice equation sanity check
# ---------------------------------------------------------------------------

def test_orifice_equation_formula():
    """
    Verify the implementation matches Q = Cd · A · √(2·g·h) exactly.
    For h=0.02 m, Cd=0.62, A=2.83e-4 m²:
      Q = 0.62 × 2.83e-4 × √(2 × 9.81 × 0.02) ≈ 1.099e-4 m³/s (~110 mL/s)

    NOTE: the original spec cited ~70.8 mL/s, which is incorrect for these
    SI parameters.  The correct value computed from Q = Cd·A·√(2gh) is
    ~109.9 mL/s.  This is greater than the 50 mL/s inflow, confirming
    that a clear drain at h=2 cm drains faster than it fills — as expected.
    """
    h = 0.02
    cd = 0.62
    a = 2.83e-4
    q = expected_outflow(cd, h, drain_area_m2=a)
    expected_q = cd * a * np.sqrt(2.0 * GRAVITY_M_S2 * h)
    assert abs(q - expected_q) < 1e-12, "Implementation must match Cd·A·√(2gh)"
    # Must exceed the 50 mL/s inflow (clear drain drains faster than it fills)
    assert q > INFLOW_RATE_M3S, (
        f"Clear drain at h=2cm (Cd=0.62) must drain faster than inflow. "
        f"Got Q={q*1e6:.1f} µL/s vs inflow={INFLOW_RATE_M3S*1e6:.1f} µL/s"
    )
    # Sanity bound: result should be in a physically reasonable range
    assert 5e-5 < q < 5e-4, f"Q={q:.3e} is outside physically plausible range"


def test_orifice_calibrated_cd_steady_state():
    """
    At the analytical steady-state depth (where Q_in == Q_out with the
    calibrated Cd), expected_outflow() should equal INFLOW_RATE_M3S.
    """
    h_ss = (INFLOW_RATE_M3S / (CALIBRATED_CD * DRAIN_AREA_M2)) ** 2 / (2.0 * GRAVITY_M_S2)
    q = expected_outflow(CALIBRATED_CD, h_ss)
    assert abs(q - INFLOW_RATE_M3S) < 1e-12, (
        f"At steady-state head, Q_out must equal Q_in. "
        f"Got Q_out={q:.4e} vs Q_in={INFLOW_RATE_M3S:.4e}"
    )


# ---------------------------------------------------------------------------
# 5. Dynamic water-level equation (Euler step)
# ---------------------------------------------------------------------------

def test_water_level_dynamics_rising():
    """Blocked drain (reduced outflow) → level rises."""
    depth = 0.02
    h = water_depth_to_hydraulic_head(depth)
    q_out = expected_outflow(CALIBRATED_CD, h, drain_area_m2=DRAIN_AREA_M2 * 0.1)
    assert INFLOW_RATE_M3S > q_out, "Partial blockage must give Q_in > Q_out"
    next_d = next_water_depth(depth, CALIBRATED_CD, dt_s=1.0,
                               q_in_m3s=INFLOW_RATE_M3S)
    # When using next_water_depth with full drain area, level falls from 2cm
    # (above ss). Test that the Euler formula is self-consistent by checking
    # a manually blocked scenario.
    rate_blocked = (INFLOW_RATE_M3S - q_out) / LAKE_AREA_M2
    assert rate_blocked > 0, "Blocked drain: level should rise"


def test_water_level_dynamics_falling():
    """Above steady state with clear drain → level falls toward steady state."""
    depth = 0.06   # well above steady state (~1.74 cm)
    next_d = next_water_depth(depth, CALIBRATED_CD, dt_s=1.0)
    assert next_d < depth, "Water level must fall toward steady state from above"


def test_euler_step_magnitude():
    depth = 0.03
    next_d = next_water_depth(depth, CALIBRATED_CD, dt_s=1.0)
    assert np.isfinite(next_d)
    assert 0.0 <= next_d <= CONTAINER_HEIGHT_M + 0.01


def test_steady_state_depth_is_fixed_point():
    """At analytical steady state, one Euler step should leave depth unchanged."""
    ss = _steady_state_depth()
    next_d = next_water_depth(ss, CALIBRATED_CD, dt_s=1.0)
    assert abs(next_d - ss) < 1e-9, (
        f"Steady-state must be a fixed point. Got drift of {abs(next_d-ss):.2e} m"
    )


# ---------------------------------------------------------------------------
# 6. Overflow at 7.5 cm
# ---------------------------------------------------------------------------

def test_overflow_at_container_height():
    assert is_overflow(CONTAINER_HEIGHT_M) is True
    assert is_overflow(CONTAINER_HEIGHT_M + 0.001) is True


def test_no_overflow_below_container_height():
    assert is_overflow(CONTAINER_HEIGHT_M - 0.001) is False
    assert is_overflow(0.02) is False


# ---------------------------------------------------------------------------
# 7. Clear drain does NOT immediately trigger blockage
# ---------------------------------------------------------------------------

def test_clear_drain_does_not_trigger_blockage():
    """
    Dynamic clear-drain simulation (depth evolves via Euler step) must
    stay in NORMAL throughout.  Using constant depth would be wrong —
    a constant depth above SS gives obs_rate=0 while pred_rate<0, which
    produces a false-positive residual.
    """
    det = BlockageDetectorState(cd=CALIBRATED_CD, q_in_m3s=INFLOW_RATE_M3S)
    final_state = _simulate_clear_drain(det, n_steps=40, start_depth=0.03)
    assert final_state == BlockageState.NORMAL, (
        f"Dynamic clear-drain should stay NORMAL, got {final_state}"
    )


def test_clear_drain_from_high_start_does_not_trigger():
    """
    Even starting at a higher depth (2.5 cm), dynamic simulation drains
    to steady state without triggering blockage.
    """
    det = BlockageDetectorState(cd=CALIBRATED_CD, q_in_m3s=INFLOW_RATE_M3S)
    final_state = _simulate_clear_drain(det, n_steps=50, start_depth=0.025)
    assert final_state == BlockageState.NORMAL, (
        f"Clear drain from 2.5cm should settle NORMAL, got {final_state}"
    )


# ---------------------------------------------------------------------------
# 8. Synthetic blockage produces persistent physics residual
# ---------------------------------------------------------------------------

def test_blockage_produces_positive_residual():
    """
    Blocked drain reduces effective area → water backs up → obs level rate
    is positive when pred rate is negative → positive residual.
    """
    det = BlockageDetectorState(cd=CALIBRATED_CD, q_in_m3s=INFLOW_RATE_M3S)
    residuals = []
    depth = _steady_state_depth()
    for _ in range(25):
        dist = _sensor_dist(depth)
        reading, _ = process_reading(det, dist, dt_s=1.0)
        if reading is not None:
            residuals.append(reading.residual)
        # Advance with reduced outflow
        h = water_depth_to_hydraulic_head(depth)
        q_out = expected_outflow(det.cd, max(h, 0.0), DRAIN_AREA_M2 * 0.15)
        depth += (det.q_in_m3s - q_out) / LAKE_AREA_M2 * 1.0
        depth = min(depth, CONTAINER_HEIGHT_M - 0.001)

    assert len(residuals) > 8
    mean_residual = float(np.mean(residuals[5:]))
    assert mean_residual > 0, (
        f"Blockage should produce positive mean residual, got {mean_residual:.4e}"
    )


def test_blockage_eventually_confirmed():
    """Sustained blockage must eventually reach BLOCKAGE_CONFIRMED."""
    det = BlockageDetectorState(cd=CALIBRATED_CD, q_in_m3s=INFLOW_RATE_M3S)
    reached = _drive_to_confirmed(det)
    assert reached, f"Expected BLOCKAGE_CONFIRMED, stuck at {det.state}"


# ---------------------------------------------------------------------------
# 9. Sensor noise does not cause false blockage
# ---------------------------------------------------------------------------

def test_sensor_noise_no_false_blockage():
    """
    Gaussian noise (±2 mm, consistent with HC-SR04 spec) around the
    dynamically-evolving clear-drain depth must not trigger blockage.

    The dynamic simulation means both obs_rate and pred_rate vary together
    so residuals stay small.  Only a SUSTAINED systematic deviation
    (not random noise) can accumulate enough signal to confirm blockage.
    """
    rng = np.random.default_rng(seed=7)
    det = BlockageDetectorState(cd=CALIBRATED_CD, q_in_m3s=INFLOW_RATE_M3S)
    depth = _steady_state_depth()
    noise_std = 0.002   # 2 mm
    for _ in range(60):
        noisy_depth = depth + rng.normal(0.0, noise_std)
        noisy_depth = max(0.001, min(noisy_depth, CONTAINER_HEIGHT_M - 0.001))
        dist = _sensor_dist(noisy_depth)
        _, state = process_reading(det, dist, dt_s=1.0)
        # True depth evolves via clear-drain physics regardless of noisy reading
        depth = next_water_depth(depth, det.cd, dt_s=1.0)
        depth = max(0.001, min(depth, CONTAINER_HEIGHT_M - 0.001))

    assert det.state == BlockageState.NORMAL, (
        f"Random HC-SR04 noise should not trigger blockage, got {det.state}"
    )


# ---------------------------------------------------------------------------
# 10. Isolation Forest: correct direction of predict() and score_samples()
# ---------------------------------------------------------------------------

def test_isolation_forest_normal_not_flagged():
    rng = np.random.default_rng(42)
    clean_windows = [list(rng.normal(0, 2, 5)) for _ in range(60)]
    clean_features = [f for w in clean_windows
                      if (f := extract_window_features(w)) is not None]
    det = BlockageAnomalyDetector(contamination=0.05)
    det.fit(clean_features)

    normal_window = [0.5, -0.3, 1.1, 0.8, 0.2]
    feats = extract_window_features(normal_window)
    assert not det.is_confirmed_anomaly(feats), \
        "Normal window must NOT be flagged as anomaly"


def test_isolation_forest_anomaly_flagged():
    rng = np.random.default_rng(42)
    clean_windows = [list(rng.normal(0, 2, 5)) for _ in range(60)]
    clean_features = [f for w in clean_windows
                      if (f := extract_window_features(w)) is not None]
    det = BlockageAnomalyDetector(contamination=0.05)
    det.fit(clean_features)

    rising_window = [5, 18, 32, 47, 65]
    feats = extract_window_features(rising_window)
    assert det.is_confirmed_anomaly(feats), \
        "Strongly rising blockage window must be flagged as anomaly"


def test_isolation_forest_score_direction():
    """
    score_samples() convention: LESS negative = more normal.
    Normal samples must score higher (less negative) than anomalies.
    """
    rng = np.random.default_rng(42)
    clean_windows = [list(rng.normal(0, 2, 5)) for _ in range(80)]
    clean_features = [f for w in clean_windows
                      if (f := extract_window_features(w)) is not None]
    det = BlockageAnomalyDetector(contamination=0.05)
    det.fit(clean_features)

    score_normal = det.anomaly_score(extract_window_features([0.5, -0.3, 1.1, 0.8, 0.2]))
    score_anomaly = det.anomaly_score(extract_window_features([10, 25, 40, 55, 70]))
    assert score_normal > score_anomaly, (
        f"Normal score ({score_normal:.4f}) must be > anomaly score ({score_anomaly:.4f})"
    )


# ---------------------------------------------------------------------------
# 11. NORMAL → BLOCKED → UNBLOCKED → CLEARING → NORMAL
# ---------------------------------------------------------------------------

def test_full_cycle_normal_blocked_clearing_normal():
    """
    The most important regression test.
    Sequence: establish NORMAL → inject blockage → confirm BLOCKAGE_CONFIRMED
              → restore clear-drain dynamics → must reach NORMAL again.

    The state machine evaluates CURRENT hydraulic behaviour — historical
    events never force the state to remain BLOCKAGE_CONFIRMED.
    """
    det = BlockageDetectorState(cd=CALIBRATED_CD, q_in_m3s=INFLOW_RATE_M3S)

    # Phase 1: establish NORMAL baseline with dynamic simulation
    _simulate_clear_drain(det, n_steps=20, start_depth=0.02)
    assert det.state == BlockageState.NORMAL, \
        f"Phase 1 (NORMAL baseline): expected NORMAL, got {det.state}"

    # Phase 2: inject blockage until CONFIRMED
    reached = _drive_to_confirmed(det)
    assert reached, \
        f"Phase 2 (blockage): expected BLOCKAGE_CONFIRMED, stuck at {det.state}"

    # Phase 3: restore clear-drain — must reach NORMAL
    reached_normal = _drive_to_normal_after_blockage(det)
    assert reached_normal, \
        f"Phase 3 (clearing): expected NORMAL, got {det.state}"


# ---------------------------------------------------------------------------
# 12. After returning to NORMAL, second blockage is detectable
# ---------------------------------------------------------------------------

def test_second_blockage_detectable_after_recovery():
    """
    NORMAL → CONFIRMED → NORMAL → CONFIRMED (second event).
    The state machine must be fully reusable with no permanent latch.
    """
    det = BlockageDetectorState(cd=CALIBRATED_CD, q_in_m3s=INFLOW_RATE_M3S)

    # First cycle
    _simulate_clear_drain(det, 20, start_depth=0.02)
    assert det.state == BlockageState.NORMAL, "First NORMAL baseline failed"

    _drive_to_confirmed(det)
    assert det.state == BlockageState.BLOCKAGE_CONFIRMED, "First blockage not confirmed"

    _drive_to_normal_after_blockage(det)
    assert det.state == BlockageState.NORMAL, \
        f"Recovery after first blockage failed: {det.state}"

    # Second cycle — system must be able to detect a new blockage
    _drive_to_confirmed(det)
    assert det.state == BlockageState.BLOCKAGE_CONFIRMED, (
        "Second blockage must be detectable — state machine must be reusable"
    )


# ---------------------------------------------------------------------------
# 13. Stale history does not keep state BLOCKED
# ---------------------------------------------------------------------------

def test_stale_history_does_not_latch_blocked():
    """
    After a blockage clears, supplying enough clear-drain readings to flush
    the residual window MUST eventually return state to NORMAL.
    Old blockage entries in the rolling window scroll out naturally.
    """
    det = BlockageDetectorState(cd=CALIBRATED_CD, q_in_m3s=INFLOW_RATE_M3S)

    _drive_to_confirmed(det)
    assert det.state == BlockageState.BLOCKAGE_CONFIRMED

    # Supply clear-drain readings — enough to flush the entire window multiple times
    _simulate_clear_drain(
        det,
        n_steps=RESIDUAL_WINDOW_SIZE * 4 + CLEAR_CONFIRMATION_SAMPLES * 3 +
                MIN_CLEARING_DURATION * 2 + 40,
    )
    assert det.state == BlockageState.NORMAL, (
        f"Stale blockage history must not permanently latch state — got {det.state}"
    )


# ---------------------------------------------------------------------------
# Legacy API compatibility
# ---------------------------------------------------------------------------

def test_calibrate_cd_basic():
    cd = calibrate_cd(200.0, 10.0, 2.0, 2.8353)
    assert 0 < cd < 2, f"Cd out of range: {cd}"


def test_calculate_area_and_blockage_pct():
    q = 20.0
    cd = 0.542
    h = 2.0
    area = calculate_area(q, cd, h)
    assert area is not None and area > 0

    # Same area compared to itself = 0% blockage
    pct_clean = blockage_percent(area, area)
    assert abs(pct_clean) < 1e-6

    # Same Q, higher head → smaller inferred area → positive blockage
    area_blocked = calculate_area(q, cd, 4.0)
    pct_blocked = blockage_percent(area_blocked, area)
    assert pct_blocked > 0, "Higher head with same Q must show positive blockage"


# ---------------------------------------------------------------------------
# Main — run all tests when executed directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    tests = [
        test_unit_conversion_depth_from_sensor,
        test_unit_conversion_inflow_si,
        test_unit_conversion_drain_area,
        test_sensor_to_depth_to_head_pipeline,
        test_invalid_sensor_distance_rejected,
        test_zero_sensor_distance_edge,
        test_zero_head_gives_zero_outflow,
        test_positive_head_gives_positive_outflow,
        test_orifice_equation_formula,
        test_orifice_calibrated_cd_steady_state,
        test_water_level_dynamics_rising,
        test_water_level_dynamics_falling,
        test_euler_step_magnitude,
        test_steady_state_depth_is_fixed_point,
        test_overflow_at_container_height,
        test_no_overflow_below_container_height,
        test_clear_drain_does_not_trigger_blockage,
        test_clear_drain_from_high_start_does_not_trigger,
        test_blockage_produces_positive_residual,
        test_blockage_eventually_confirmed,
        test_sensor_noise_no_false_blockage,
        test_isolation_forest_normal_not_flagged,
        test_isolation_forest_anomaly_flagged,
        test_isolation_forest_score_direction,
        test_full_cycle_normal_blocked_clearing_normal,
        test_second_blockage_detectable_after_recovery,
        test_stale_history_does_not_latch_blocked,
        test_calibrate_cd_basic,
        test_calculate_area_and_blockage_pct,
    ]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"✓ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed.")
