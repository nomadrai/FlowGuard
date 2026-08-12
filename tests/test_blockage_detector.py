"""
Basic tests for blockage_detector module.
Currently uses the module's built-in self-tests.
"""
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

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
    
    print("\nAll tests passed!")
