"""
Basic tests for blockage_detector module.
Currently uses the module's built-in self-tests.
"""
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'flowguard'))

from flowguard import blockage_detector
import numpy as np


def test_calibrate_cd():
    """Test discharge coefficient calibration."""
    # Example calibration data (in cm/mL units as used by module)
    pour_volume_ml = 500.0   # mL (500 mL)
    pour_time_sec = 10.0     # seconds
    steady_height_cm = 8.0   # cm (8 cm)
    clean_area_cm2 = 12.0    # cm² (12 cm²)

    cd = blockage_detector.calibrate_cd(
        pour_volume_ml, pour_time_sec, steady_height_cm, clean_area_cm2
    )

    # Cd should be positive and reasonable (typically 0.6-0.8 for clean orifices,
    # but our channels have friction so ~0.05-0.1 is expected)
    assert cd > 0, "Cd should be positive"
    assert cd < 1, "Cd should be less than 1"


def test_compute_blockage_pct():
    """Test blockage percentage calculation."""
    # Use the same parameters from the module's self-test
    cd = 0.0543
    clean_area_cm2 = 12.0    # cm²

    # Clean channel scenario: same height as calibration
    height_cm = 8.0          # cm
    inflow_cm3_s = 50.0      # cm³/s (500 mL / 10 sec)

    # Calculate effective area
    calculated_area = blockage_detector.calculate_area(inflow_cm3_s, cd, height_cm)

    # Calculate blockage percentage
    blockage_pct = blockage_detector.blockage_percent(calculated_area, clean_area_cm2)

    # Blockage should be a percentage
    assert isinstance(blockage_pct, float), "Blockage should be a float"

    # Blocked channel scenario: higher water with same inflow
    height_blocked_cm = 10.0
    calculated_area_blocked = blockage_detector.calculate_area(inflow_cm3_s, cd, height_blocked_cm)
    blockage_pct_blocked = blockage_detector.blockage_percent(calculated_area_blocked, clean_area_cm2)

    # Blocked channel should show positive blockage
    assert blockage_pct_blocked > 0, "Blocked channel should show positive blockage %"
    assert blockage_pct_blocked > blockage_pct, "Blocked channel should show higher blockage than clean"


def test_ml_confirm_blockage():
    """Test ML confirmation layer."""
    # The ML layer is tested in the module's own self-test.
    # Here we just verify the basic API works.
    detector = blockage_detector.BlockageAnomalyDetector(contamination=0.15)

    # Create training data
    clean_windows = [
        [3.0, 4.0, 5.0, 4.0, 3.0, 4.0, 5.0, 4.0, 3.0, 4.0],
        [4.0, 5.0, 3.0, 4.0, 5.0, 4.0, 3.0, 5.0, 4.0, 3.0],
        [5.0, 4.0, 3.0, 4.0, 5.0, 3.0, 4.0, 5.0, 4.0, 3.0],
    ]

    # Extract features and fit
    clean_features = [blockage_detector.extract_window_features(w) for w in clean_windows]
    detector.fit(clean_features)

    # Verify detector can process a window
    test_window = [5.0, 4.0, 3.0, 4.0, 5.0, 4.0, 3.0, 4.0, 5.0, 4.0]
    test_features = blockage_detector.extract_window_features(test_window)
    is_anomaly = detector.is_confirmed_anomaly(test_features)

    # Just verify it returns a boolean (the exact result depends on the model)
    assert isinstance(is_anomaly, (bool, np.bool_)), "Should return boolean"
    print(f"✓ ML detector API working (test window anomaly status: {is_anomaly})")


def test_forecast_days_to_critical():
    """Test trend forecasting."""
    blockage_history = [10.0, 15.0, 20.0, 25.0, 30.0, 35.0]
    timestamps_days = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]  # Day 0 through Day 5
    critical_threshold = 50.0

    days = blockage_detector.forecast_days_to_critical(
        blockage_history, timestamps_days, critical_threshold
    )

    # Should return a positive number of days
    assert days is not None, "Should return a forecast"
    assert days > 0, "Days should be positive"

    # With this rising trend (5% per day), should reach 50% in ~3 more days from day 5
    assert 0 < days < 30, f"Forecast of {days} days seems unreasonable"


def _levels_from_rates(rates, start=0.0):
    """Water levels (cm) built from consecutive rise rates (cm per reading)."""
    levels = [start]
    for r in rates:
        levels.append(levels[-1] + r)
    return levels


def test_rate_based_detection_clear_on_normal_rise():
    """Steady normal rise (+1 -> +1.1 -> +1 cm/reading) must stay CLEAR."""
    levels = _levels_from_rates([1.0, 1.1, 1.0, 1.0, 1.1, 1.0, 1.0, 1.05])
    r = blockage_detector.detect_blockage_from_rise(
        levels, min_readings=5, recent_window=3, baseline_window=3
    )
    assert r["verdict"] == "CLEAR", r


def test_rate_based_detection_blockage_on_acceleration():
    """A sudden jump in rise rate (+1 -> +2.5 -> +3 cm/reading) is a blockage."""
    levels = _levels_from_rates([1.0, 1.1, 1.0, 1.0, 1.1, 1.0, 2.5, 3.0, 3.0])
    r = blockage_detector.detect_blockage_from_rise(
        levels, min_readings=5, recent_window=3, baseline_window=3
    )
    assert r["verdict"] == "BLOCKAGE_DETECTED", r


def test_rate_based_detection_clear_when_water_falls():
    """A falling water level (+3 -> +2 -> +0.5 -> -0.5) means the blockage
    has been cleared — must show CLEAR again."""
    levels = _levels_from_rates([1.0, 1.0, 1.0, 3.0, 3.0, 2.0, 0.5, -0.5, -0.5])
    r = blockage_detector.detect_blockage_from_rise(
        levels, min_readings=5, recent_window=3, baseline_window=3
    )
    assert r["verdict"] == "CLEAR", r


def test_rate_based_detection_ignores_absolute_level():
    """The SAME rise-rate pattern at very different absolute water levels must
    give the SAME verdict — detection is about rate, never absolute height."""
    rates = [1.0, 1.0, 1.0, 3.0, 3.0]
    r_low = blockage_detector.detect_blockage_from_rise(
        _levels_from_rates(rates, start=2.0), min_readings=5, recent_window=2, baseline_window=2
    )
    r_high = blockage_detector.detect_blockage_from_rise(
        _levels_from_rates(rates, start=20.0), min_readings=5, recent_window=2, baseline_window=2
    )
    assert r_low["verdict"] == "BLOCKAGE_DETECTED", r_low
    assert r_high["verdict"] == "BLOCKAGE_DETECTED", r_high


def test_rate_based_detection_insufficient_data_is_clear():
    """Too few readings to learn the normal rise rate must never alarm."""
    r = blockage_detector.detect_blockage_from_rise([1.0, 1.1, 1.2, 1.3])
    assert r["verdict"] == "CLEAR", r


def test_reference_height_tracker_never_rebaselines_on_rise():
    """A water-level RISE (a possible blockage) must never move the reference."""
    tracker = blockage_detector.ReferenceHeightTracker(initial_fixed_height_cm=20.0)
    tracker.update(20.0)
    assert tracker.update(21.5) is None
    assert tracker.fixed_height == 20.0
    assert not tracker.decrease_detected


def test_clear_filter_ignores_isolated_single_decreases():
    """A single sudden decrease (sensor glitch) must never clear a live blockage."""
    f = blockage_detector.ClearConfirmationFilter()
    f.update(5.0, raw_blocked=True)   # blockage active
    f.update(5.2, raw_blocked=True)
    assert f.update(4.1, raw_blocked=False) == "BLOCKAGE DETECTED"  # dip #1 — ignored
    f.update(5.3, raw_blocked=True)
    assert f.update(4.2, raw_blocked=False) == "BLOCKAGE DETECTED"  # another isolated dip
    assert f.update(5.4, raw_blocked=True) == "BLOCKAGE DETECTED"
    assert f.blocked  # blockage latch is still held


def test_clear_filter_confirms_after_3_consecutive_decreases():
    """CLEAR requires 3 consecutive decreasing readings, even when the raw
    pipeline already says clear."""
    f = blockage_detector.ClearConfirmationFilter()
    f.update(6.0, raw_blocked=True)   # blockage active
    f.update(6.2, raw_blocked=True)
    f.update(6.4, raw_blocked=True)
    assert f.update(6.0, raw_blocked=False) == "BLOCKAGE DETECTED"  # decrease 1
    assert f.update(5.5, raw_blocked=False) == "BLOCKAGE DETECTED"  # decrease 2
    assert f.update(5.0, raw_blocked=False) == "CLEAR"              # decrease 3 -> confirmed
    assert f.update(4.5, raw_blocked=False) == "CLEAR"              # streak continues
    assert not f.blocked


def test_clear_filter_streak_resets_on_rise():
    """Any rise or plateau between dips resets the consecutive streak."""
    f = blockage_detector.ClearConfirmationFilter()
    f.update(6.0, raw_blocked=True)
    f.update(5.5, raw_blocked=True)
    f.update(5.0, raw_blocked=True)
    assert f.update(5.2, raw_blocked=False) == "BLOCKAGE DETECTED"  # rise resets the streak
    f.update(4.9, raw_blocked=False)   # 1st decrease after the reset
    assert f.update(4.6, raw_blocked=False) == "BLOCKAGE DETECTED"  # only 2 so far
    assert f.update(4.3, raw_blocked=False) == "CLEAR"              # 3rd consecutive


def test_clear_filter_never_blocked_stays_clear():
    """No blockage ever flagged: CLEAR verdicts pass straight through."""
    f = blockage_detector.ClearConfirmationFilter()
    assert f.update(3.0, raw_blocked=False) == "CLEAR"
    assert f.update(2.8, raw_blocked=False) == "CLEAR"
    assert f.update(3.1, raw_blocked=False) == "CLEAR"
    assert not f.blocked


if __name__ == "__main__":
    print("Running blockage_detector tests...")
    test_calibrate_cd()
    print("✓ test_calibrate_cd passed")
    
    test_compute_blockage_pct()
    print("✓ test_compute_blockage_pct passed")
    
    test_ml_confirm_blockage()
    print("✓ test_ml_confirm_blockage passed")
    
    test_forecast_days_to_critical()
    print("✓ test_forecast_days_to_critical passed")

    test_rate_based_detection_clear_on_normal_rise()
    print("✓ test_rate_based_detection_clear_on_normal_rise passed")

    test_rate_based_detection_blockage_on_acceleration()
    print("✓ test_rate_based_detection_blockage_on_acceleration passed")

    test_rate_based_detection_clear_when_water_falls()
    print("✓ test_rate_based_detection_clear_when_water_falls passed")

    test_rate_based_detection_ignores_absolute_level()
    print("✓ test_rate_based_detection_ignores_absolute_level passed")

    test_rate_based_detection_insufficient_data_is_clear()
    print("✓ test_rate_based_detection_insufficient_data_is_clear passed")

    test_reference_height_tracker_never_rebaselines_on_rise()
    print("✓ test_reference_height_tracker_never_rebaselines_on_rise passed")

    test_clear_filter_ignores_isolated_single_decreases()
    print("✓ test_clear_filter_ignores_isolated_single_decreases passed")

    test_clear_filter_confirms_after_3_consecutive_decreases()
    print("✓ test_clear_filter_confirms_after_3_consecutive_decreases passed")

    test_clear_filter_streak_resets_on_rise()
    print("✓ test_clear_filter_streak_resets_on_rise passed")

    test_clear_filter_never_blocked_stays_clear()
    print("✓ test_clear_filter_never_blocked_stays_clear passed")

    print("\nAll tests passed!")
